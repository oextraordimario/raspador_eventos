"""Atualização sob demanda da base de eventos — o comando único da Fase 0.

Fluxo: raspa as 5 fontes (Sympla, Ingresse, Shotgun, Zig, Ticket and Go;
tolerante a falha por fonte) → upsert (guardando o payload bruto na camada
Bronze) → marcar sumidos (evento futuro que não reapareceu no catálogo) →
descrever (busca incremental da descrição p/ eventos sem ela) → precificar
(tickets/lotes de Sympla, Ingresse, Zig e Ticket and Go, refeito a cada
rodada porque preço é volátil — dentro de uma janela de 30 dias) →
cinema (grade dos 8 cinemas via Ingresso.com, snapshot → cinema_raw; depois
da derivação, o enriquecimento TMDB incremental — sinopse/nota/ano por filme
NOVO → cinema_extra_raw, NI-36) →
instagram (posts/stories da watchlist via Monid → instagram_raw + extração
do flyer por visão, incremental) → derivar (colunas calculadas do bruto, sem
rede; inclui filmes/sessoes e eventos fonte='instagram') → enriquecimento v1
(ruído + dedupe, recalculado do zero — o dedupe concilia post ↔ evento de
plataforma) → reconstrói o FTS → relatório de saúde (com comparação vs.
rodada anterior) → grava a rodada em `execucoes` (NI-19).

Uso (da raiz do repo):
    python src/atualizar.py                    # pipeline completo
    python src/atualizar.py --sem-shotgun      # pula o Shotgun (lento, usa navegador)
    python src/atualizar.py --sem-cinema       # pula a grade de cinema
    python src/atualizar.py --sem-tmdb         # pula o enriquecimento TMDB dos filmes
    python src/atualizar.py --sem-instagram    # pula o Instagram (Monid/claude -p)
    python src/atualizar.py --precificar-tudo  # tickets de TODOS os futuros (ex.: 1ª carga)
    python src/atualizar.py --so-derivar       # não raspa; re-deriva do bruto + regras + FTS
    python src/atualizar.py --so-enriquecer    # não raspa; só reaplica regras + FTS
"""

import json
import re
import socket
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import derivar
import enriquecer
import midia
import store
import tempo
from scrapers import (cinema, ingresse, instagram, shotgun, sympla,
                      ticketandgo, tmdb, zig)

# Rede com IPv6 quebrado (opt-in, FORCAR_IPV4=1 no env): urllib e psycopg
# tentam os endereços IPv6 em SEQUÊNCIA (sem happy eyeballs do navegador/curl)
# e pagam ~20s de timeout por endereço antes de cair no IPv4 — uma rodada de
# 200 descrições viraria horas. O filtro no getaddrinfo derruba cada request
# de ~50s para ~0.2s na rede afetada; fora dela, nada muda (por isso opt-in).
# Visto na máquina do autor em 2026-07-27 (Neon e BFF do Sympla).
if store.env_var("FORCAR_IPV4"):
    _getaddrinfo = socket.getaddrinfo

    def _so_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return _getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = _so_ipv4
    print("[rede] FORCAR_IPV4=1 — resolvendo só endereços IPv4")

# Preço/lote é volátil, mas quem pergunta ao agente pergunta de "hoje"/"este
# fim de semana": o precificar só refaz eventos nesta janela; os demais mantêm
# o último preço derivado até entrarem nela (--precificar-tudo cobre todos).
JANELA_PRECIFICAR_DIAS = 30

# Queda de coleta vs. rodada anterior que dispara alerta no relatório
# (provável scraper quebrado). Calibrar se der falso positivo.
QUEDA_ALERTA = 0.5

# Post mais velho que isso não vale extração de flyer (evento já passou ou
# está na base desde a rodada em que o post era novo): protege a 1ª rodada de
# um perfil novo de gastar visão com o feed histórico.
EXTRAIR_POSTS_DIAS = 60


def _checar_schema(con):
    """Base de schema antigo não é migrada automaticamente — mas TAMBÉM não é
    descartável: a Bronze mora nela (convenção revista em 2026-07-27; ver o
    cabeçalho de sql/schema.sql)."""
    cols = {r["column_name"] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'eventos'")}
    if "ruido" not in cols or "sumido" not in cols:
        sys.exit("A base é de um schema antigo.\nNÃO rode DROP SCHEMA (a "
                 "camada Bronze mora nesse banco e não se reconstrói). Aplique "
                 "a diferença com ALTER TABLE no DBeaver/psql usando "
                 "sql/schema.sql como referência e execute de novo.")


def _raspar(incluir_shotgun=True):
    """Raspa cada fonte isoladamente: uma fonte quebrada não esconde as outras.

    A conexão com a base abre DEPOIS de cada raspagem e fecha logo após o
    upsert (2026-07-27): raspar um catálogo leva minutos, e conexão parada
    esse tempo todo é derrubada pela rede em silêncio — foi o Zig quebrando
    a rodada inteira. Conexão curta é barata; mantê-la viva é cilada.
    """
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
            con = store.conectar()
            try:
                store.upsert_eventos(con, eventos)
            finally:
                con.close()
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

    Instagram fica FORA (guarda explícita, além da ordem dos passos no main):
    o feed do perfil não é um catálogo de eventos futuros — post que sai da
    1ª página não significa cancelamento; evento do Instagram morre por data
    passada. Spec: 20260723_instagram-como-fonte §2.6.

    Fonte que coletou ZERO também fica fora (NI-59, 2026-07-28): coleta vazia
    não é catálogo vazio. O Shotgun devolveu 0 COM sucesso por três rodadas no
    CI e escondeu a agenda inteira dele da consulta. Catálogo de plataforma de
    ingresso não esvazia de um dia para o outro; quando esvazia de verdade, os
    eventos morrem por data passada — que já não é marcado. O falso negativo
    (evento cancelado demora um dia a mais para sumir) é ordens de grandeza
    mais barato que o falso positivo. Spec: 20260728_fontes-quebradas §3.3.
    """
    inicio = tempo.instante(iniciada_em)
    sumidos = []
    for fonte, res in resultados.items():
        if "erro" in res or fonte in ("instagram", "cinema"):
            continue
        if not res.get("coletados"):
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


def _raspar_cinema(erros):
    """Raspa a grade dos cinemas e grava o snapshot na Bronze (cinema_raw).

    Falha por cinema×dia entra em `erros` e NÃO substitui o payload anterior
    daquele par (buraco não apaga grade boa); falha total vira {"erro"} no
    resultado, como as outras fontes. Quem deriva filmes/sessoes é o
    derivar.aplicar_cinema, no passo seguinte. A conexão abre só DEPOIS da
    raspagem (minutos de rede) — conexão parada cai; curta, não.
    """
    print(f"\n[cinema] grade de {len(cinema.CINEMAS)} cinemas (Ingresso.com)...")
    try:
        r = cinema.raspar()
    except Exception as e:
        traceback.print_exc()
        print("[cinema] FALHOU — grade anterior mantida.")
        return {"erro": f"{type(e).__name__}: {e}"}
    con = store.conectar()
    try:
        store.gravar_cinema_raw(con, r["raw"],
                                datetime.now(timezone.utc).isoformat())
    finally:
        con.close()
    for falha in r["erros"]:
        erros.append({"passo": "cinema",
                      "evento_id": f"{falha['cinema']} {falha['dia']}",
                      "erro": falha["erro"]})
    return dict(cinema.ULTIMA_RASPAGEM)


def _raspar_instagram(erros, extrair=True):
    """Posts/stories da watchlist → Bronze (instagram_raw) + extração do
    flyer dos posts novos (visão via `claude -p`, incremental — a fila é o
    shortcode sem origem='extracao'; falha re-tenta na próxima rodada).

    Conexões CURTAS (2026-07-27): uma para gravar a Bronze e montar a fila,
    e uma POR GRAVAÇÃO na extração — cada flyer leva ~1 min de visão e uma
    conexão parada esse tempo cai. De quebra, cada extração agora persiste
    na hora: falhar no post 5 não perde os 4 anteriores (antes o commit era
    um só no fim).

    A mídia é baixada AGORA porque a URL do CDN expira em horas; a Bronze
    recém-gravada garante URL fresca até para post pendente de rodada
    anterior. Quem transforma post em evento é derivar.aplicar_instagram.

    `extrair=False` (flag --sem-extracao-flyer) faz a coleta parar na Bronze:
    raspa os perfis, grava os posts e NÃO chama a visão. É o modo do cron
    (spec 20260726_abrir-ao-publico §3 passo 2, "caminho 1"): o `claude -p`
    roda na ASSINATURA e não há login de assinatura em CI. A fila é
    incremental e re-tentável por desenho, então o que ficou pendente é
    extraído na próxima rodada LOCAL — o resultado reporta quantos são, para
    o pendente não virar invisível.
    """
    perfis = instagram.watchlist_ativos()
    if not perfis:
        print("\n[instagram] watchlist vazia ou ausente "
              "(dados/perfis_instagram.yaml) — pulando.")
        return None
    print(f"\n[instagram] {len(perfis)} perfis da watchlist (via Monid)...")
    try:
        r = instagram.raspar(perfis)
    except Exception as e:
        traceback.print_exc()
        print("[instagram] FALHOU — dados anteriores mantidos.")
        return {"erro": f"{type(e).__name__}: {e}"}
    con = store.conectar()
    try:
        store.gravar_instagram_raw(con, r["raw"],
                                   datetime.now(timezone.utc).isoformat())
        for f in r["erros"]:
            erros.append({"passo": "instagram", "evento_id": f"@{f['perfil']}",
                          "erro": f["erro"]})
        resultado = dict(instagram.ULTIMA_RASPAGEM)

        corte = (datetime.now(timezone.utc)
                 - timedelta(days=EXTRAIR_POSTS_DIAS)).timestamp()
        alvos, antigos = [], 0
        # fila: post sem extração OU com extração do formato antigo marcada
        # e_evento=false — candidato a carrossel-agenda que a regra pré-v1.1
        # descartava (backfill dirigido, spec §8.5; instagram.extracao_pendente).
        for row in con.execute(
                "SELECT p.perfil, p.code, p.payload, x.payload AS ext "
                "FROM instagram_raw p "
                "LEFT JOIN instagram_raw x "
                "  ON x.code = p.code AND x.origem = 'extracao' "
                "WHERE p.origem = 'post' ORDER BY p.code").fetchall():
            if not instagram.extracao_pendente(
                    json.loads(row["ext"]) if row["ext"] else None):
                continue
            post = json.loads(row["payload"])
            if (post.get("taken_at") or 0) < corte:
                antigos += 1
                continue
            alvos.append((row, post))
    finally:
        con.close()
    if not extrair:
        # Caminho 1: a Bronze está atualizada, a visão fica para a rodada
        # local. Não é erro nem falha — é escopo do cron.
        print(f"[instagram] extração do flyer PULADA (--sem-extracao-flyer): "
              f"{len(alvos)} posts aguardando a próxima rodada local.")
        resultado.update(extraidos=None, falhas_extracao=None,
                         pendentes_extracao=len(alvos))
        return resultado

    extraidos = falhas = 0
    if alvos:
        print(f"[instagram] extraindo eventos de {len(alvos)} posts "
              "(claude -p, visão; todas as páginas do carrossel)..."
              + (f" — {antigos} posts com mais de {EXTRAIR_POSTS_DIAS} dias "
                 "ficam sem extração" if antigos else ""))
    for row, post in alvos:
        caminhos = []
        try:
            caminhos = instagram.baixar_midias(post)
        except Exception as e:
            erros.append({"passo": "instagram",
                          "evento_id": f"instagram:{row['code']}",
                          "erro": f"mídia (seguiu com {len(caminhos)} páginas"
                                  f" + legenda): {type(e).__name__}: {e}"})
        try:
            ext = instagram.extrair(instagram.legenda_do_post(post), caminhos)
            con = store.conectar()
            try:
                store.gravar_instagram_raw(
                    con, [(row["perfil"], row["code"], "extracao", ext)],
                    datetime.now(timezone.utc).isoformat())
            finally:
                con.close()
            extraidos += 1
        except Exception as e:
            falhas += 1
            erros.append({"passo": "instagram",
                          "evento_id": f"instagram:{row['code']}",
                          "erro": f"extração: {type(e).__name__}: {e}"})
    if alvos:
        print(f"  {extraidos} flyers extraídos | {falhas} falhas "
              "(re-tentam na próxima rodada)")
    resultado.update(extraidos=extraidos, falhas_extracao=falhas)
    return resultado


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


def _relatorio(con, resultados, derivado, cine, insta, enriq, sumidos,
               duracao):
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
                # O alerta diz também o que o sistema FEZ a respeito: com
                # coleta zerada o _marcar_sumidos pula a fonte (NI-59), então
                # os eventos dela continuam visíveis na consulta.
                if atual == 0:
                    print(f"      coleta ZERADA — sumidos NÃO recalculados "
                          f"para {nome} (os eventos seguem visíveis)")
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

    # --- instagram: eventos derivados de instagram_raw (post + extração) ---
    if insta is not None:
        res = resultados.get("instagram") or {}
        cobertura = (f" de {res['coletados']}/{res['total_site']} perfis"
                     if "coletados" in res else "")
        print(f"\nInstagram (watchlist{cobertura}): {insta['eventos']} eventos"
              f" derivados, {insta['lotes']} com preço no flyer"
              f" ({insta['descartados']} posts sem evento pela guarda)")
        # Caminho 1 (cron): a visão não roda em CI. Sem esta linha, o pendente
        # ficaria invisível justamente na rodada que não o processa.
        if res.get("pendentes_extracao"):
            print(f"  *** {res['pendentes_extracao']} posts aguardando "
                  "extração do flyer — rode `python src/atualizar.py "
                  "--so-instagram` localmente (a visão exige a assinatura)")

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


def _enriquecer_cinema(con, erros):
    """Passo TMDB (NI-36), incremental: busca sinopse/nota/ano para filme em
    cartaz que ainda não tem linha origem='tmdb' na Bronze cinema_extra_raw
    — 1 chamada por filme NOVO (o id da Ingresso.com é estável), então após
    o backfill inicial são poucas por semana. Roda DEPOIS da derivação (a
    lista de filmes em cartaz é a própria tabela) e o chamador re-deriva se
    algo foi buscado. Falha por filme não grava nada e re-tenta na próxima
    rodada. Sem TMDB_API_KEY o passo é pulado com aviso (não é erro).
    """
    chave = store.env_var("TMDB_API_KEY")
    if not chave:
        print("\n[tmdb] TMDB_API_KEY ausente — filmes seguem sem sinopse/nota.")
        return None
    pendentes = con.execute(
        "SELECT f.id, f.titulo, f.titulo_original FROM filmes f "
        "LEFT JOIN cinema_extra_raw x "
        "  ON x.filme_id = f.id AND x.origem = 'tmdb' "
        "WHERE x.filme_id IS NULL ORDER BY f.titulo").fetchall()
    if not pendentes:
        return 0
    print(f"\n[tmdb] enriquecendo {len(pendentes)} filme(s) novo(s)...")
    agora = datetime.now(timezone.utc).isoformat()
    buscados = com_match = 0
    for f in pendentes:
        try:
            payload = tmdb.raspar_filme(f["titulo"], f["titulo_original"],
                                        chave)
        except Exception as e:
            erros.append({"passo": "tmdb", "evento_id": f["id"],
                          "erro": f"{type(e).__name__}: {e}"})
            continue
        store.gravar_cinema_extra(con, f["id"], "tmdb", payload, agora)
        buscados += 1
        if payload.get("escolhido"):
            com_match += 1
        time.sleep(0.25)
    print(f"  {buscados} buscados, {com_match} com match confiável "
          f"(sem match não ganha nota — auditoria na Bronze)")
    return buscados


def _copiar_posters(con, erros):
    """Passo pôster (NI-37), incremental: filme em cartaz cujo pôster ainda
    não tem cópia própria (origem='poster' na cinema_extra_raw) é baixado do
    CDN da fonte e re-hospedado no Blob com pathname estável. O front prefere
    `poster_proprio` e cai no hotlink enquanto a cópia não existe.
    """
    if not midia.token():
        print("\n[poster] BLOB_READ_WRITE_TOKEN ausente — hotlink mantido.")
        return None
    pendentes = con.execute(
        "SELECT f.id, f.poster FROM filmes f "
        "LEFT JOIN cinema_extra_raw x "
        "  ON x.filme_id = f.id AND x.origem = 'poster' "
        "WHERE f.poster IS NOT NULL AND x.filme_id IS NULL "
        "ORDER BY f.id").fetchall()
    if not pendentes:
        return 0
    print(f"\n[poster] copiando {len(pendentes)} pôster(es) para o storage...")
    agora = datetime.now(timezone.utc).isoformat()
    n = 0
    for f in pendentes:
        try:
            dados, ctype = midia.baixar(f["poster"])
            ext = midia.EXTENSOES.get(ctype, "jpg")
            url = midia.subir(dados, f"posters/{f['id']}.{ext}", ctype)
        except Exception as e:
            erros.append({"passo": "poster", "evento_id": f["id"],
                          "erro": f"{type(e).__name__}: {e}"})
            continue
        store.gravar_cinema_extra(con, f["id"], "poster", {"url": url}, agora)
        n += 1
        time.sleep(0.2)
    print(f"  {n} copiados")
    return n


def _subir_midias_instagram(con, erros):
    """Flyer do Instagram para o storage próprio (NI-34, via infra do NI-37):
    a raspagem já baixa a mídia para midias/instagram/ (a URL do CDN expira em
    horas); aqui o arquivo local de post que ainda não tem origem='midia' na
    Bronze sobe para o Blob, e a derivação grava a URL em eventos.imagem.
    """
    if not midia.token():
        return None
    pendentes = con.execute(
        "SELECT p.perfil, p.code FROM instagram_raw p "
        "LEFT JOIN instagram_raw m ON m.code = p.code AND m.origem = 'midia' "
        "WHERE p.origem = 'post' AND m.code IS NULL ORDER BY p.code").fetchall()
    agora = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in pendentes:
        arquivos = sorted(instagram.MIDIAS.glob(f"{r['code']}*"))
        imagens = [a for a in arquivos
                   if a.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        if not imagens:
            continue  # mídia não baixada (post antigo): fica para a próxima
        arq = imagens[0]  # capa do post (1ª página do carrossel)
        ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "png": "image/png", "webp": "image/webp"}[arq.suffix[1:].lower()]
        try:
            url = midia.subir(arq.read_bytes(),
                              f"instagram/{r['code']}{arq.suffix.lower()}", ctype)
        except Exception as e:
            erros.append({"passo": "midia-instagram", "evento_id": r["code"],
                          "erro": f"{type(e).__name__}: {e}"})
            continue
        store.gravar_instagram_raw(
            con, [(r["perfil"], r["code"], "midia", {"url": url})], agora)
        n += 1
    if n:
        print(f"\n[midia] {n} flyer(s) do Instagram no storage próprio")
    return n


def main():
    inicio = time.monotonic()
    iniciada_em = datetime.now(timezone.utc).isoformat()
    so_enriquecer = "--so-enriquecer" in sys.argv
    so_derivar = "--so-derivar" in sys.argv
    so_instagram = "--so-instagram" in sys.argv
    sem_shotgun = "--sem-shotgun" in sys.argv
    sem_cinema = "--sem-cinema" in sys.argv
    sem_instagram = "--sem-instagram" in sys.argv
    sem_extracao = "--sem-extracao-flyer" in sys.argv
    modo = ("so-enriquecer" if so_enriquecer else "so-derivar" if so_derivar
            else "so-instagram" if so_instagram
            else "cron" if sem_extracao
            else "sem-shotgun" if sem_shotgun else "completo")

    # Conexões CURTAS por bloco (2026-07-27, a pedido do autor): o pipeline
    # intercala minutos de raspagem/visão com escrita na base, e conexão
    # parada é derrubada pela rede em silêncio (SSL closed no meio da rodada,
    # visto no Zig). Cada bloco abre a sua e fecha; os passos de raspagem
    # abrem as próprias depois da rede. Alongar a vida da conexão é cilada.
    con = store.conectar()
    _checar_schema(con)
    con.close()

    resultados, erros = {}, []
    sumidos = desc = prec = None
    if not (so_enriquecer or so_derivar):
        # --so-instagram: rodada curta que processa só a fila de extração
        # deixada pelo cron (que roda com --sem-extracao-flyer). Re-raspa os
        # perfis de propósito — a URL de mídia do CDN expira em horas, então
        # a Bronze precisa estar fresca para a visão conseguir baixar o flyer.
        if not so_instagram:
            resultados = _raspar(incluir_shotgun=not sem_shotgun)
            if resultados and all("erro" in r for r in resultados.values()):
                sys.exit("Todas as fontes falharam — base não atualizada.")
            # sumidos primeiro: cinema não entra em resultados ainda (grade não
            # tem sumido — sessão que sai simplesmente não volta no snapshot).
            # descrever/precificar tocam a base a cada evento — os gaps são
            # curtos, uma conexão para o bloco basta.
            con = store.conectar()
            sumidos = _marcar_sumidos(con, resultados, iniciada_em)
            desc = _descrever(con, erros)
            prec = _precificar(con, erros,
                               tudo="--precificar-tudo" in sys.argv)
            con.close()
            if not sem_cinema:
                resultados["cinema"] = _raspar_cinema(erros)
        # depois do _marcar_sumidos de propósito: a fonte instagram fica FORA
        # da lógica de sumido (post que sai da 1ª página do perfil não
        # significa cancelamento — evento do Instagram morre por data passada).
        if not sem_instagram:
            r_insta = _raspar_instagram(erros, extrair=not sem_extracao)
            if r_insta is not None:
                resultados["instagram"] = r_insta

    # daqui em diante é derivação/enriquecimento/relatório: conexão nova —
    # a raspagem acima pode ter levado muitos minutos.
    con = store.conectar()

    # --so-enriquecer reaplica só as regras (não mexe nas colunas derivadas);
    # o fluxo normal e o --so-derivar recalculam as derivadas a partir da
    # Bronze. aplicar_instagram roda DEPOIS de aplicar() (que trunca lotes).
    derivado = None if so_enriquecer else derivar.aplicar(con)
    insta = None if so_enriquecer else derivar.aplicar_instagram(con)
    cine = None if so_enriquecer else derivar.aplicar_cinema(con)

    # TMDB e cópia de pôster depois da derivação (a lista do que está em
    # cartaz É a tabela) e só em rodada que raspou; se algo novo chegou à
    # Bronze, re-deriva para aplicar — aplicar_cinema é idempotente e custa
    # segundos. O flyer do Instagram sobe antes do aplicar_instagram pelo
    # mesmo motivo (a derivação é quem grava eventos.imagem).
    if (not (so_enriquecer or so_derivar or so_instagram)
            and not sem_cinema and "--sem-tmdb" not in sys.argv):
        novos = _enriquecer_cinema(con, erros) or 0
        novos += _copiar_posters(con, erros) or 0
        if novos:
            cine = derivar.aplicar_cinema(con)
    if not (so_enriquecer or so_derivar):
        if _subir_midias_instagram(con, erros):
            insta = derivar.aplicar_instagram(con)

    enriq = enriquecer.aplicar(con, aliases_local=instagram.aliases_local())
    store.reconstruir_fts(con)
    duracao = time.monotonic() - inicio
    # O relatório lê execucoes ANTES do registro: a comparação é com a rodada
    # anterior de verdade, não com esta.
    _relatorio(con, resultados, derivado, cine, insta, enriq, sumidos, duracao)
    store.registrar_execucao(
        con, iniciada_em, round(duracao, 1), modo, resultados,
        {"descrever": desc, "precificar": prec, "derivado": derivado,
         "cinema": cine, "instagram": insta, "ruido": len(enriq["ruido"]),
         "dedupe_grupos": len(enriq["grupos"]),
         "sumidos": len(sumidos) if sumidos is not None else None},
        erros)
    con.close()


if __name__ == "__main__":
    main()
