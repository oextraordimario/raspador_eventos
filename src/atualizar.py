"""Atualização sob demanda da base de eventos — o comando único da Fase 0.

Fluxo: raspa as 3 fontes (tolerante a falha por fonte) → upsert (guardando o
payload bruto na camada Bronze) → descrever (busca incremental da descrição p/
eventos sem ela) → precificar (tickets/lotes de Sympla e Ingresse, refeito a
cada rodada porque preço é volátil) → derivar (colunas calculadas do bruto,
sem rede) → enriquecimento v1 (ruído + dedupe, recalculado do zero) →
reconstrói o FTS → relatório de saúde.

Uso (da raiz do repo):
    python src/atualizar.py                  # pipeline completo
    python src/atualizar.py --sem-shotgun    # pula o Shotgun (lento, usa navegador)
    python src/atualizar.py --so-derivar     # não raspa; re-deriva do bruto + regras + FTS
    python src/atualizar.py --so-enriquecer  # não raspa; só reaplica regras + FTS
"""

import re
import sys
import time
import traceback
from datetime import datetime, timezone

import derivar
import enriquecer
import store
from scrapers import ingresse, shotgun, sympla


def _checar_schema(con):
    """Base criada antes de uma mudança de schema não é migrada: é descartável."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(eventos)")}
    if "ruido" not in cols or "tem_gratis" not in cols:
        sys.exit("A base data/eventos.db é de um schema antigo.\nNa Fase 0 a base "
                 "é descartável: apague o arquivo e rode de novo para re-raspar.")


def _raspar(con, incluir_shotgun=True):
    """Raspa cada fonte isoladamente: uma fonte quebrada não esconde as outras."""
    fontes = [
        ("sympla", sympla, lambda: sympla.raspar(
            city="brasilia", state="DF", location="Brasília", max_paginas=10)),
        ("ingresse", ingresse, lambda: ingresse.raspar()),
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


def _descrever(con, pausa=0.4):
    """Busca a descrição dos eventos que ainda não têm (incremental: o upsert
    preserva descrição já colhida, então só os novos custam requisição).

    Shotgun já traz descrição na raspagem (JSON-LD); Sympla e Ingresse têm
    endpoints de evento individual (ver raspar_descricao de cada scraper).
    """
    # URLs do Bileto (bileto.sympla.com.br) ficam de fora: o id no fim delas é
    # de outro namespace e o BFF de página devolveria outro evento (NI-17).
    pendentes = con.execute(
        "SELECT id, fonte, nome, url FROM eventos "
        "WHERE descricao IS NULL AND fonte IN ('sympla', 'ingresse') "
        "AND url IS NOT NULL AND url NOT LIKE '%bileto.sympla.com.br%'").fetchall()
    if not pendentes:
        return {"buscadas": 0, "falhas": 0}
    print(f"\n[descrever] {len(pendentes)} eventos sem descrição...")
    buscadas = falhas = trocados = 0
    for i, r in enumerate(pendentes, 1):
        try:
            if r["fonte"] == "sympla":
                # id numérico no fim da URL pública (difere do id do catálogo)
                m = re.search(r"/(\d+)/?$", r["url"])
                if not m:
                    falhas += 1
                    continue
                d = sympla.raspar_descricao(m.group(1))
                if not _mesmo_nome(r["nome"], d["nome"]):
                    trocados += 1
                    continue  # payload suspeito não entra nem na Bronze
                con.execute(
                    "UPDATE eventos SET descricao = ?, "
                    "categoria = COALESCE(?, categoria) WHERE id = ?",
                    (d["descricao"], d.get("categoria"), r["id"]))
            else:  # ingresse: slug no fim da URL pública
                slug = r["url"].rstrip("/").rsplit("/", 1)[-1]
                d = ingresse.raspar_descricao(slug)
                con.execute("UPDATE eventos SET descricao = ? WHERE id = ?",
                            (d["descricao"], r["id"]))
            store.gravar_raw(con, r["id"], "detalhe", d["payload"],
                             datetime.now(timezone.utc).isoformat(),
                             commit=False)
            buscadas += 1 if d["descricao"] else 0
        except Exception:
            falhas += 1
        if i % 50 == 0:
            print(f"  {i}/{len(pendentes)}...")
        time.sleep(pausa)
    con.commit()
    print(f"  {buscadas} descrições gravadas | {falhas} falhas/sem descrição"
          + (f" | {trocados} descartadas por nome divergente (id trocado?)"
             if trocados else ""))
    return {"buscadas": buscadas, "falhas": falhas, "trocados": trocados}


def _precificar(con, pausa=0.3):
    """Busca o payload de tickets (preço/lotes) de Sympla e Ingresse e grava na
    Bronze (origem='tickets'); quem transforma em preco_min/esgotado é o
    derivar. NÃO é incremental: preço/lote muda entre rodadas, então refaz
    todos os eventos futuros a cada atualização.

    Sympla: só eventos com descrição validada — o endpoint de tickets não
    devolve nome para a guarda do NI-17, então a descrição validada é a âncora
    de que o id não está trocado. Shotgun não precisa deste passo (as offers
    já vêm no JSON-LD do catálogo).
    """
    agora = datetime.now(timezone.utc)
    alvos = []
    for r in con.execute(
            "SELECT id, fonte, id_nativo, url, start_date, descricao "
            "FROM eventos WHERE fonte IN ('sympla', 'ingresse')"):
        dt = _instante(r["start_date"])
        if not dt or dt < agora:
            continue
        if r["fonte"] == "sympla" and (
                not r["descricao"] or "bileto.sympla.com.br" in (r["url"] or "")):
            continue  # sem âncora contra id trocado (NI-17) — fica sem preço
        alvos.append(r)
    if not alvos:
        return {"buscados": 0, "falhas": 0}
    print(f"\n[precificar] tickets de {len(alvos)} eventos futuros "
          f"(Sympla/Ingresse)...")
    buscados = falhas = 0
    for i, r in enumerate(alvos, 1):
        try:
            if r["fonte"] == "sympla":
                m = re.search(r"/(\d+)/?$", r["url"] or "")
                if not m:
                    falhas += 1
                    continue
                t = sympla.raspar_tickets(m.group(1))
            else:
                t = ingresse.raspar_tickets(r["id_nativo"])
            store.gravar_raw(con, r["id"], "tickets", t["payload"],
                             datetime.now(timezone.utc).isoformat(),
                             commit=False)
            buscados += 1
        except Exception:
            falhas += 1
        if i % 50 == 0:
            print(f"  {i}/{len(alvos)}...")
        time.sleep(pausa)
    con.commit()
    print(f"  {buscados} payloads de tickets gravados | {falhas} falhas")
    return {"buscados": buscados, "falhas": falhas}


def _instante(iso):
    dt = None
    if iso:
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return None
    if dt and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc) if dt else None


def _relatorio(con, resultados, derivado, enriq, duracao):
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

    # --- base: totais e janela futura por fonte ---
    rows = con.execute("SELECT fonte, start_date, ruido FROM eventos").fetchall()
    futuros = {}
    for r in rows:
        dt = _instante(r["start_date"])
        if dt and dt >= agora and not r["ruido"]:
            futuros.setdefault(r["fonte"], []).append(dt)
    total = len(rows)
    print(f"\nBase ({store.DB_PATH.name}): {total} eventos, "
          f"{sum(len(v) for v in futuros.values())} futuros (sem contar ruído)")
    print("  janela futura por fonte:")
    for fonte in sorted(futuros):
        ds = sorted(futuros[fonte])
        print(f"    {fonte:<9} {ds[0].date()} → {ds[-1].date()}  ({len(ds)} eventos)")

    # --- campos ricos: % com descrição e preço por fonte ---
    print("  descrição preenchida por fonte:")
    for fonte, com, tot in con.execute(
            "SELECT fonte, SUM(descricao IS NOT NULL), COUNT(*) "
            "FROM eventos GROUP BY fonte ORDER BY fonte"):
        print(f"    {fonte:<9} {com}/{tot}  ({100 * com // tot}%)")
    print("  preço mínimo preenchido por fonte (eventos futuros):")
    stats = {}
    for r in con.execute("SELECT fonte, start_date, preco_min FROM eventos"):
        dt = _instante(r["start_date"])
        if not dt or dt < agora:
            continue
        com, tot = stats.get(r["fonte"], (0, 0))
        stats[r["fonte"]] = (com + (r["preco_min"] is not None), tot + 1)
    for fonte in sorted(stats):
        com, tot = stats[fonte]
        print(f"    {fonte:<9} {com}/{tot}  ({100 * com // tot}%)")

    # --- camada Bronze: payloads brutos e colunas derivadas ---
    raws = con.execute("SELECT origem, COUNT(*) FROM eventos_raw "
                       "GROUP BY origem ORDER BY origem").fetchall()
    print("  payloads brutos (Bronze): " +
          (", ".join(f"{origem}: {n}" for origem, n in raws) or "nenhum"))
    if derivado is not None:
        derivado = dict(derivado)
        lotes_n = derivado.pop("lotes", 0)
        print("  colunas derivadas do bruto: " +
              ", ".join(f"{c}: {n} eventos" for c, n in derivado.items()))
        print(f"  lotes de ingresso (tabela lotes): {lotes_n}")

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
    so_enriquecer = "--so-enriquecer" in sys.argv
    so_derivar = "--so-derivar" in sys.argv

    con = store.conectar()
    _checar_schema(con)

    resultados = {}
    if not (so_enriquecer or so_derivar):
        resultados = _raspar(con, incluir_shotgun="--sem-shotgun" not in sys.argv)
        if resultados and all("erro" in r for r in resultados.values()):
            con.close()
            sys.exit("Todas as fontes falharam — base não atualizada.")
        _descrever(con)
        _precificar(con)

    # --so-enriquecer reaplica só as regras (não mexe nas colunas derivadas);
    # o fluxo normal e o --so-derivar recalculam as derivadas a partir da Bronze.
    derivado = None if so_enriquecer else derivar.aplicar(con)

    enriq = enriquecer.aplicar(con)
    store.reconstruir_fts(con)
    _relatorio(con, resultados, derivado, enriq, time.monotonic() - inicio)
    con.close()


if __name__ == "__main__":
    main()
