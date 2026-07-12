"""Atualização sob demanda da base de eventos — o comando único da Fase 0.

Fluxo: raspa as 5 fontes (Sympla, Ingresse, Shotgun, Zig, Ticket and Go;
tolerante a falha por fonte) → upsert (guardando o payload bruto na camada
Bronze) → marcar sumidos (evento futuro que não reapareceu no catálogo) →
descrever (busca incremental da descrição p/ eventos sem ela) → precificar
(tickets/lotes de Sympla, Ingresse, Zig e Ticket and Go, refeito a cada
rodada porque preço é volátil — dentro de uma janela de 30 dias) →
cinema (grade dos 8 cinemas via Ingresso.com, snapshot → cinema_raw) →
derivar (colunas calculadas do bruto, sem rede; inclui filmes/sessoes) →
enriquecimento v1 (ruído + dedupe, recalculado do zero) → reconstrói o FTS →
relatório de saúde (com comparação vs. rodada anterior) → grava a rodada em
`execucoes` (NI-19).

Uso (da raiz do repo):
    python src/atualizar.py                    # pipeline completo
    python src/atualizar.py --sem-shotgun      # pula o Shotgun (lento, usa navegador)
    python src/atualizar.py --sem-cinema       # pula a grade de cinema
    python src/atualizar.py --precificar-tudo  # tickets de TODOS os futuros (ex.: 1ª carga)
    python src/atualizar.py --so-derivar       # não raspa; re-deriva do bruto + regras + FTS
    python src/atualizar.py --so-enriquecer    # não raspa; só reaplica regras + FTS
"""

import json
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import derivar
import enriquecer
import store
import tempo
from scrapers import cinema, ingresse, shotgun, sympla, ticketandgo, zig

# Preço/lote é volátil, mas quem pergunta ao agente pergunta de "hoje"/"este
# fim de semana": o precificar só refaz eventos nesta janela; os demais mantêm
# o último preço derivado até entrarem nela (--precificar-tudo cobre todos).
JANELA_PRECIFICAR_DIAS = 30

# Queda de coleta vs. rodada anterior que dispara alerta no relatório
# (provável scraper quebrado). Calibrar se der falso positivo.
QUEDA_ALERTA = 0.5


def _checar_schema(con):
    """Base criada antes de uma mudança de schema não é migrada: é descartável."""
    cols = {r["column_name"] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'eventos'")}
    if "ruido" not in cols or "sumido" not in cols:
        sys.exit("A base é de um schema antigo.\nNa Fase 0 a base é descartável: "
                 "rode `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` no "
                 "banco (DBeaver/psql) e execute de novo para re-raspar.")


def _raspar(con, incluir_shotgun=True):
    """Raspa cada fonte isoladamente: uma fonte quebrada não esconde as outras."""
    fontes = [
        ("sympla", sympla, lambda: sympla.raspar(
            city="brasilia", state="DF", location="Brasília", max_paginas=10)),
        ("ingresse", ingresse, lambda: ingresse.raspar()),
        ("zig", zig, lambda: zig.raspar(estado="DF")),
        ("ticketandgo", ticketandgo, lambda: ticketandgo.raspar()),
    ]
    if incluir_shotgun:
        fontes.append(("shotgun", shotgun,
                       lambda: shotgun.raspar(city_slug="brasilia")))

    resultados = {}
    for nome, modulo, chamada in fontes:
        print(f"\n[{nome}] raspando...")
        try:
            eventos = chamada()
            store.upsert_eventos(con, eventos)
            resultados[nome] = dict(modulo.ULTIMA_RASPAGEM)
        except Exception as e:
            traceback.print_exc()
            resultados[nome] = {"erro": f"{type(e).__name__}: {e}"}
            print(f"[{nome}] FALHOU — seguindo com as outras fontes.")
    return resultados


def _mesmo_nome(a, b):
    """Confere se dois nomes de evento são o mesmo (caixa/espaços à parte).

    Proteção contra id trocado (NI-17): o BFF do Sympla devolve um evento
    VÁLIDO de outro namespace (Bileto) — e às vezes de URL comum — sem erro
    HTTP; sem esta checagem, descrição e categoria alheias entram caladas na
    base. Aceita relação de prefixo (até 20 chars) nos dois sentidos porque a
    página pode usar um nome mais curto que o catálogo ("DOMINGÃO" vs
    "DOMINGÃO | PARTE 2" — caso real de 2026-07-10). Calibrada no spike da
    Bronze (tests/spike_bronze/) + primeira rodada em produção.
    """
    na, nb = (re.sub(r"\s+", " ", (s or "").casefold()).strip() for s in (a, b))
    if not na or not nb:
        return False
    return na.startswith(nb[:20]) or nb.startswith(na[:20])


def _marcar_sumidos(con, resultados, iniciada_em):
    """Recalcula `sumido` por fonte raspada SEM erro nesta rodada: evento
    FUTURO cujo raspado_em ficou para trás não reapareceu no catálogo —
    provável remoção/cancelamento silencioso, que o payload não avisa.

    Fonte que falhou não condena seus eventos (um 500 do Sympla não pode
    esconder a agenda inteira). Evento passado nunca é marcado (catálogo só
    lista futuros; marcá-lo apagaria o histórico da consulta). Idempotente:
    quem reaparece no upsert é desmarcado aqui. Marcar, não apagar — quem
    esconde é a consulta. Spec: 20260710_alinhamento-constituicao.
    """
    inicio = tempo.instante(iniciada_em)
    sumidos = []
    for fonte, res in resultados.items():
        if "erro" in res:
            continue
        for r in con.execute("SELECT id, nome, start_date, raspado_em "
                             "FROM eventos WHERE fonte = %s", (fonte,)).fetchall():
            dt = tempo.instante(r["start_date"])
            visto = tempo.instante(r["raspado_em"])
            sumido = 1 if (dt and dt >= inicio
                           and (not visto or visto < inicio)) else 0
            con.execute("UPDATE eventos SET sumido = %s WHERE id = %s",
                        (sumido, r["id"]))
            if sumido:
                sumidos.append((r["nome"], fonte))
    con.commit()
    return sumidos


def _descrever(con, erros, pausa=0.4):
    """Busca a descrição dos eventos que ainda não têm (incremental: o upsert
    preserva descrição já colhida, então só os novos custam requisição).

    Shotgun e Ticket and Go já trazem descrição na raspagem (JSON-LD /
    catálogo); Sympla, Ingresse e Zig têm endpoints de evento individual (ver
    raspar_descricao de cada scraper). Falha por evento entra em `erros` (vai
    para execucoes.erros), além do contador — padrão sistemático precisa ser
    visível.
    """
    # URLs do Bileto ficam de fora: o id no fim delas é de outro namespace e o
    # BFF de página devolveria outro evento (NI-17). Sumidos não valem requisição.
    pendentes = con.execute(
        "SELECT id, fonte, nome, url FROM eventos "
        "WHERE descricao IS NULL AND fonte IN ('sympla', 'ingresse', 'zig') "
        "AND sumido = 0 AND url IS NOT NULL AND url NOT LIKE %s",
        (f"%{sympla.BILETO_HOST}%",)).fetchall()
    if not pendentes:
        return {"buscadas": 0, "falhas": 0}
    print(f"\n[descrever] {len(pendentes)} eventos sem descrição...")
    buscadas = falhas = trocados = 0
    for i, r in enumerate(pendentes, 1):
        try:
            if r["fonte"] == "sympla":
                id_url = sympla.id_da_url(r["url"])
                if not id_url:
                    falhas += 1
                    erros.append({"passo": "descrever", "evento_id": r["id"],
                                  "erro": "URL sem id numérico no fim"})
                    continue
                d = sympla.raspar_descricao(id_url)
                if not _mesmo_nome(r["nome"], d["nome"]):
                    trocados += 1
                    erros.append({"passo": "descrever", "evento_id": r["id"],
                                  "erro": "nome divergente do BFF (id trocado? "
                                          "NI-17) — payload descartado"})
                    continue  # payload suspeito não entra nem na Bronze
                con.execute(
                    "UPDATE eventos SET descricao = %s, "
                    "categoria = COALESCE(%s, categoria) WHERE id = %s",
                    (d["descricao"], d.get("categoria"), r["id"]))
            elif r["fonte"] == "zig":  # slug no fim da URL pública
                slug = r["url"].rstrip("/").rsplit("/", 1)[-1]
                d = zig.raspar_descricao(slug)
                if not _mesmo_nome(r["nome"], d["nome"]):
                    trocados += 1
                    erros.append({"passo": "descrever", "evento_id": r["id"],
                                  "erro": "nome divergente da API — payload "
                                          "descartado"})
                    continue  # payload suspeito não entra nem na Bronze
                con.execute("UPDATE eventos SET descricao = %s WHERE id = %s",
                            (d["descricao"], r["id"]))
            else:  # ingresse: slug no fim da URL pública
                slug = r["url"].rstrip("/").rsplit("/", 1)[-1]
                d = ingresse.raspar_descricao(slug)
                con.execute("UPDATE eventos SET descricao = %s WHERE id = %s",
                            (d["descricao"], r["id"]))
            store.gravar_raw(con, r["id"], "detalhe", d["payload"],
                             datetime.now(timezone.utc).isoformat(),
                             commit=False)
            buscadas += 1 if d["descricao"] else 0
        except Exception as e:
            falhas += 1
            erros.append({"passo": "descrever", "evento_id": r["id"],
                          "erro": f"{type(e).__name__}: {e}"})
        if i % 50 == 0:
            print(f"  {i}/{len(pendentes)}...")
        time.sleep(pausa)
    con.commit()
    print(f"  {buscadas} descrições gravadas | {falhas} falhas/sem descrição"
          + (f" | {trocados} descartadas por nome divergente (id trocado?)"
             if trocados else ""))
    return {"buscadas": buscadas, "falhas": falhas, "trocados": trocados}


def _precificar(con, erros, pausa=0.3, tudo=False):
    """Busca o payload de tickets (preço/lotes) de Sympla e Ingresse e grava na
    Bronze (origem='tickets'); quem transforma em preco_min/esgotado é o
    derivar. NÃO é incremental (preço/lote muda entre rodadas), mas refaz só
    os eventos na janela de JANELA_PRECIFICAR_DIAS — quem fica fora mantém o
    último preço derivado até entrar nela (tudo=True cobre todos os futuros).

    Sympla: só eventos com descrição validada — o endpoint de tickets não
    devolve nome para a guarda do NI-17, então a descrição validada é a âncora
    de que o id não está trocado. Zig: lê o __NEXT_DATA__ da página pública
    (NI-23) e valida o nome devolvido. Shotgun não precisa deste passo (as
    offers já vêm no JSON-LD do catálogo).
    """
    agora = datetime.now(timezone.utc)
    limite = agora + timedelta(days=JANELA_PRECIFICAR_DIAS)
    alvos, fora_janela = [], 0
    for r in con.execute(
            "SELECT id, fonte, id_nativo, nome, url, start_date, descricao "
            "FROM eventos WHERE fonte IN ('sympla', 'ingresse', 'zig', "
            "'ticketandgo') AND sumido = 0"):
        dt = tempo.instante(r["start_date"])
        if not dt or dt < agora:
            continue
        if r["fonte"] == "sympla" and (
                not r["descricao"] or not sympla.id_da_url(r["url"])):
            continue  # sem âncora contra id trocado (NI-17) — fica sem preço
        if not tudo and dt > limite:
            fora_janela += 1  # sem teto silencioso: o log diz quantos ficaram fora
            continue
        alvos.append(r)
    if not alvos:
        return {"buscados": 0, "falhas": 0, "fora_janela": fora_janela}
    escopo = ("todos os futuros" if tudo
              else f"próximos {JANELA_PRECIFICAR_DIAS} dias")
    print(f"\n[precificar] tickets de {len(alvos)} eventos ({escopo}, "
          f"Sympla/Ingresse/Zig/Ticket and Go)"
          + (f" — {fora_janela} futuros fora da janela mantêm o último preço"
             if fora_janela else "") + "...")
    buscados = falhas = 0
    for i, r in enumerate(alvos, 1):
        try:
            if r["fonte"] == "sympla":
                t = sympla.raspar_tickets(sympla.id_da_url(r["url"]))
            elif r["fonte"] == "zig":  # página pública (slug no fim da URL)
                t = zig.raspar_tickets(r["url"].rstrip("/").rsplit("/", 1)[-1])
                if not _mesmo_nome(r["nome"], t.get("nome")):
                    falhas += 1
                    erros.append({"passo": "precificar", "evento_id": r["id"],
                                  "erro": "nome divergente da página — "
                                          "payload descartado"})
                    continue  # payload suspeito não entra nem na Bronze
            elif r["fonte"] == "ticketandgo":  # slug no fim da URL pública
                t = ticketandgo.raspar_tickets(
                    r["url"].rstrip("/").rsplit("/", 1)[-1])
            else:
                t = ingresse.raspar_tickets(r["id_nativo"])
            store.gravar_raw(con, r["id"], "tickets", t["payload"],
                             datetime.now(timezone.utc).isoformat(),
                             commit=False)
            buscados += 1
        except Exception as e:
            falhas += 1
            erros.append({"passo": "precificar", "evento_id": r["id"],
                          "erro": f"{type(e).__name__}: {e}"})
        if i % 50 == 0:
            print(f"  {i}/{len(alvos)}...")
        time.sleep(pausa)
    con.commit()
    print(f"  {buscados} payloads de tickets gravados | {falhas} falhas")
    return {"buscados": buscados, "falhas": falhas, "fora_janela": fora_janela}


def _raspar_cinema(con, erros):
    """Raspa a grade dos cinemas e grava o snapshot na Bronze (cinema_raw).

    Falha por cinema×dia entra em `erros` e NÃO substitui o payload anterior
    daquele par (buraco não apaga grade boa); falha total vira {"erro"} no
    resultado, como as outras fontes. Quem deriva filmes/sessoes é o
    derivar.aplicar_cinema, no passo seguinte.
    """
    print(f"\n[cinema] grade de {len(cinema.CINEMAS)} cinemas (Ingresso.com)...")
    try:
        r = cinema.raspar()
    except Exception as e:
        traceback.print_exc()
        print("[cinema] FALHOU — grade anterior mantida.")
        return {"erro": f"{type(e).__name__}: {e}"}
    store.gravar_cinema_raw(con, r["raw"],
                            datetime.now(timezone.utc).isoformat())
    for falha in r["erros"]:
        erros.append({"passo": "cinema",
                      "evento_id": f"{falha['cinema']} {falha['dia']}",
                      "erro": falha["erro"]})
    return dict(cinema.ULTIMA_RASPAGEM)


def _coleta_anterior(con):
    """Última coleta registrada por fonte em execucoes: {fonte: (coletados,
    iniciada_em)}. Ignora rodadas em que a fonte falhou ou não foi raspada —
    a comparação do relatório só faz sentido coleta contra coleta."""
    ant = {}
    for r in con.execute(
            "SELECT iniciada_em, fontes FROM execucoes ORDER BY id DESC"):
        for nome, dados in json.loads(r["fontes"] or "{}").items():
            if nome not in ant and isinstance(dados.get("coletados"), int):
                ant[nome] = (dados["coletados"], r["iniciada_em"])
    return ant


def _relatorio(con, resultados, derivado, cine, enriq, sumidos, duracao):
    agora = datetime.now(timezone.utc)
    print("\n" + "=" * 64)
    print(f"Saúde da base — {agora.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 64)

    # --- fontes / cobertura ---
    print("\nFontes (coletados/total no site):")
    if not resultados:
        print("  raspagem pulada (--so-derivar/--so-enriquecer)")
    for nome, r in resultados.items():
        if "erro" in r:
            print(f"  {nome:<9} FALHOU: {r['erro']}")
        else:
            print(f"  {nome:<9} {r.get('coletados', '?')}/{r.get('total_site', '?')}")

    # --- vs. rodada anterior (detector de scraper quebrado em silêncio) ---
    if resultados:
        anterior = _coleta_anterior(con)
        for nome, r in resultados.items():
            if not isinstance(r.get("coletados"), int) or nome not in anterior:
                continue
            antes, quando = anterior[nome]
            atual = r["coletados"]
            if antes > 0 and atual < antes * (1 - QUEDA_ALERTA):
                pct = 100 - 100 * atual // antes
                print(f"  *** ALERTA {nome}: coleta caiu {pct}% "
                      f"({antes} → {atual}; rodada anterior "
                      f"{quando[:16]}) — scraper quebrado?")
            else:
                print(f"  {nome:<9} vs. rodada anterior: {antes} → {atual}")

    # --- base: totais e janela futura por fonte ---
    rows = con.execute("SELECT fonte, start_date, ruido FROM eventos").fetchall()
    futuros = {}
    for r in rows:
        dt = tempo.instante(r["start_date"])
        if dt and dt >= agora and not r["ruido"]:
            futuros.setdefault(r["fonte"], []).append(dt)
    total = len(rows)
    banco = con.execute("SELECT current_database() AS db").fetchone()["db"]
    print(f"\nBase ({banco} no Neon): {total} eventos, "
          f"{sum(len(v) for v in futuros.values())} futuros (sem contar ruído)")
    print("  janela futura por fonte:")
    for fonte in sorted(futuros):
        ds = sorted(futuros[fonte])
        print(f"    {fonte:<9} {ds[0].date()} → {ds[-1].date()}  ({len(ds)} eventos)")

    # --- campos ricos: % com descrição e preço por fonte ---
    print("  descrição preenchida por fonte:")
    for r in con.execute(
            "SELECT fonte, COUNT(descricao) AS com, COUNT(*) AS tot "
            "FROM eventos GROUP BY fonte ORDER BY fonte"):
        print(f"    {r['fonte']:<9} {r['com']}/{r['tot']}  "
              f"({100 * r['com'] // r['tot']}%)")
    print("  preço mínimo preenchido por fonte (eventos futuros):")
    stats = {}
    for r in con.execute("SELECT fonte, start_date, preco_min FROM eventos"):
        dt = tempo.instante(r["start_date"])
        if not dt or dt < agora:
            continue
        com, tot = stats.get(r["fonte"], (0, 0))
        stats[r["fonte"]] = (com + (r["preco_min"] is not None), tot + 1)
    for fonte in sorted(stats):
        com, tot = stats[fonte]
        print(f"    {fonte:<9} {com}/{tot}  ({100 * com // tot}%)")

    # --- camada Bronze: payloads brutos e colunas derivadas ---
    raws = con.execute("SELECT origem, COUNT(*) AS n FROM eventos_raw "
                       "GROUP BY origem ORDER BY origem").fetchall()
    print("  payloads brutos (Bronze): " +
          (", ".join(f"{r['origem']}: {r['n']}" for r in raws) or "nenhum"))
    if derivado is not None:
        derivado = dict(derivado)
        lotes_n = derivado.pop("lotes", 0)
        print("  colunas derivadas do bruto: " +
              ", ".join(f"{c}: {n} eventos" for c, n in derivado.items()))
        print(f"  lotes de ingresso (tabela lotes): {lotes_n}")

    # --- cinema: grade derivada de cinema_raw (snapshot da rodada) ---
    if cine is not None:
        res = resultados.get("cinema") or {}
        cobertura = (f" em {res['coletados']}/{res['total_site']} cinemas"
                     if "coletados" in res else "")
        print(f"\nCinema (grade da Ingresso.com): {cine['filmes']} filmes, "
              f"{cine['sessoes']} sessões{cobertura}")

    # --- sumidos do catálogo (só quando houve raspagem nesta rodada) ---
    if sumidos is not None:
        print(f"\nSumidos do catálogo da fonte (escondidos da consulta): "
              f"{len(sumidos)}")
        for nome, fonte in sumidos:
            print(f'  - "{(nome or "")[:70]}"  [{fonte}]')

    # --- enriquecimento ---
    ruido, grupos = enriq["ruido"], enriq["grupos"]
    print(f"\nRuído marcado (some da consulta): {len(ruido)}")
    for nome, termo in ruido:
        print(f'  - "{nome[:70]}"  [{termo}]')
    print(f"\nDuplicatas cross-fonte colapsadas: {len(grupos)} grupo(s)")
    for grupo in grupos:
        canon = grupo[0]
        print(f'  - "{(canon["nome"] or "")[:60]}" [{canon["fonte"]}]  ←  ' +
              "; ".join(f'"{(m["nome"] or "")[:45]}" [{m["fonte"]}]'
                        for m in grupo[1:]))

    print(f"\nÍndice de busca reconstruído. Duração: {duracao:.0f}s.")
    print('Pronto — pergunte ao agente: "o que tem hoje em Brasília?"')


def main():
    inicio = time.monotonic()
    iniciada_em = datetime.now(timezone.utc).isoformat()
    so_enriquecer = "--so-enriquecer" in sys.argv
    so_derivar = "--so-derivar" in sys.argv
    sem_shotgun = "--sem-shotgun" in sys.argv
    sem_cinema = "--sem-cinema" in sys.argv
    modo = ("so-enriquecer" if so_enriquecer else "so-derivar" if so_derivar
            else "sem-shotgun" if sem_shotgun else "completo")

    con = store.conectar()
    _checar_schema(con)

    resultados, erros = {}, []
    sumidos = desc = prec = None
    if not (so_enriquecer or so_derivar):
        resultados = _raspar(con, incluir_shotgun=not sem_shotgun)
        if resultados and all("erro" in r for r in resultados.values()):
            con.close()
            sys.exit("Todas as fontes falharam — base não atualizada.")
        # sumidos primeiro: cinema não entra em resultados ainda (grade não
        # tem sumido — sessão que sai simplesmente não volta no snapshot).
        sumidos = _marcar_sumidos(con, resultados, iniciada_em)
        desc = _descrever(con, erros)
        prec = _precificar(con, erros, tudo="--precificar-tudo" in sys.argv)
        if not sem_cinema:
            resultados["cinema"] = _raspar_cinema(con, erros)

    # --so-enriquecer reaplica só as regras (não mexe nas colunas derivadas);
    # o fluxo normal e o --so-derivar recalculam as derivadas a partir da Bronze.
    derivado = None if so_enriquecer else derivar.aplicar(con)
    cine = None if so_enriquecer else derivar.aplicar_cinema(con)

    enriq = enriquecer.aplicar(con)
    store.reconstruir_fts(con)
    duracao = time.monotonic() - inicio
    # O relatório lê execucoes ANTES do registro: a comparação é com a rodada
    # anterior de verdade, não com esta.
    _relatorio(con, resultados, derivado, cine, enriq, sumidos, duracao)
    store.registrar_execucao(
        con, iniciada_em, round(duracao, 1), modo, resultados,
        {"descrever": desc, "precificar": prec, "derivado": derivado,
         "cinema": cine, "ruido": len(enriq["ruido"]),
         "dedupe_grupos": len(enriq["grupos"]),
         "sumidos": len(sumidos) if sumidos is not None else None},
        erros)
    con.close()


if __name__ == "__main__":
    main()
