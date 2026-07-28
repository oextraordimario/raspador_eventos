"""Atualização sob demanda da base de eventos — o comando único da Fase 0.

DOIS TEMPOS, e a fronteira entre eles é o desenho inteiro (spec
20260728_arquitetura-medalhao §8): **tudo que tem rede é coleta, tudo que é a
seco é tratamento, e só o tratamento escreve em `tratado`**.

  1. COLETA — raspa as 5 fontes (tolerante a falha por fonte) → grava o payload
     em `cru.<fonte>` e o registro da coleta em `operacao.coletas` → descrever
     (payload de detalhe dos que ainda não têm) → precificar (payload de tickets
     dos futuros na janela de 30 dias; não é incremental, preço é volátil) →
     cinema (grade dos 8 cinemas) → instagram (posts/stories + extração do flyer
     por visão) → flyer no storage próprio.
  2. TRATAMENTO — `tratamento/ciclo.py`, numa transação só: reconstrói
     `tratado` inteira a partir do cru, deriva `sumido` de `operacao.coletas`,
     enriquece (ruído + dedupe cross-fonte), reaplica a curadoria humana e
     reconstrói o FTS.

Depois: TMDB e cópia de pôster (que só sabem o que buscar depois de a grade
existir, então rodam entre um ciclo e outro), poda do histórico do cru,
relatório de saúde (com comparação vs. rodada anterior) e o registro da rodada
em `operacao.execucoes` (NI-19).

Uso (da raiz do repo):
    python src/pipeline/atualizar.py                    # pipeline completo
    python src/pipeline/atualizar.py --sem-shotgun      # pula o Shotgun (lento, usa navegador)
    python src/pipeline/atualizar.py --sem-cinema       # pula a grade de cinema
    python src/pipeline/atualizar.py --sem-tmdb         # pula o enriquecimento TMDB dos filmes
    python src/pipeline/atualizar.py --sem-instagram    # pula o Instagram (Monid/claude -p)
    python src/pipeline/atualizar.py --precificar-tudo  # tickets de TODOS os futuros (ex.: 1ª carga)
    python src/pipeline/atualizar.py --so-derivar       # não raspa; reconstrói `tratado` do cru
    python src/pipeline/atualizar.py --so-enriquecer    # não raspa; só reaplica regras + FTS
"""

import json
import socket
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

from pathlib import Path

# Entrypoint: põe src/ no sys.path para os pacotes de estágio resolverem
# (namespace packages, sem __init__.py). Rodar da raiz do repo:
#     python src/pipeline/atualizar.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from base import conexao, tempo, texto                            # noqa: E402
from coleta import (cinema, gravar, ingresse, instagram, midias,  # noqa: E402
                    shotgun, sympla, ticketandgo, tmdb, zig)
from pipeline import execucoes                                    # noqa: E402
from tratamento import ciclo, comum, curadoria, sumido            # noqa: E402
# `cinema` e `instagram` existem nos DOIS estágios — coleta/ sabe falar com a
# fonte, tratamento/ sabe ler o payload dela. Aqui só a coleta é importada: o
# lado do tratamento roda inteiro dentro de `ciclo.executar`.

# Rede com IPv6 quebrado (opt-in, FORCAR_IPV4=1 no env): urllib e psycopg
# tentam os endereços IPv6 em SEQUÊNCIA (sem happy eyeballs do navegador/curl)
# e pagam ~20s de timeout por endereço antes de cair no IPv4 — uma rodada de
# 200 descrições viraria horas. O filtro no getaddrinfo derruba cada request
# de ~50s para ~0.2s na rede afetada; fora dela, nada muda (por isso opt-in).
# Visto na máquina do autor em 2026-07-27 (Neon e BFF do Sympla).
if conexao.env_var("FORCAR_IPV4"):
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

# Janela do histórico append-only do `cru`. Passado isso, sobra só a última
# versão de cada (id_nativo, origem) — nunca o estado atual.
#
# 90 dias porque o dedupe por hash NÃO segura o crescimento tanto quanto
# parece: o `global_score` do Sympla muda todo dia e o `currentAvailableQty`
# dos tickets muda a cada ingresso vendido, então há versão nova quase toda
# rodada (~2,7 MB/rodada, ≈1 GB/ano sem poda). Com 90 dias estabiliza em
# ~250 MB, levando a branch do Neon a ~60% do teto de 512 MiB — que é POR
# BRANCH, e a branch carrega quatro bancos. O degrau, se apertar, é 30 dias
# (~80 MB). Spec 20260728_arquitetura-medalhao §3.5.
JANELA_HISTORICO_DIAS = 90


def _checar_schema(con):
    """Base de schema antigo não é migrada automaticamente — mas TAMBÉM não é
    descartável: a camada cru mora nela (convenção revista em 2026-07-27; ver
    o cabeçalho de sql/cru/eventos_raw.sql)."""
    cols = {r["column_name"] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'tratado' AND table_name = 'eventos'")}
    if "ruido" not in cols or "sumido" not in cols:
        sys.exit("A base é de um schema antigo.\nNÃO rode DROP SCHEMA (a "
                 "camada cru mora nesse banco e não se reconstrói). Aplique "
                 "a diferença com ALTER TABLE no DBeaver/psql usando os "
                 "arquivos de sql/ como referência e execute de novo.")


def _raspar(incluir_shotgun=True, apenas=None, locais_df=None):
    """Raspa cada fonte isoladamente: uma fonte quebrada não esconde as outras.

    Escreve em `cru.<fonte>` (o payload) e em `operacao.coletas` (o registro da
    coleta) — **nunca em `tratado`**. Quem transforma payload em evento é
    `tratamento/comum.aplicar`, depois, a seco. Até 2026-07-28 esta função
    chamava o upsert da prata e por isso a prata não se reconstruía (NI-55).

    `apenas` restringe a nomes de fonte (é como a rodada local pega só o
    Shotgun, que não funciona no CI — ver `--rodada-local` no main).

    `locais_df` é a referência canônica de casas (lida de `curado.locais` pelo
    main): quem conhece a base é o pipeline, não o coletor.

    O `raspado_em` de todos os payloads da rodada é o INÍCIO da coleta daquela
    fonte, o mesmo instante gravado em `operacao.coletas.iniciada_em` — é o que
    faz a comparação do `sumido` ser exata (quem foi coletado agora tem
    `visto_em` igual ao início; quem não foi, menor).

    A conexão com a base abre DEPOIS de cada raspagem e fecha logo em seguida
    (2026-07-27): raspar um catálogo leva minutos, e conexão parada esse tempo
    todo é derrubada pela rede em silêncio — foi o Zig quebrando a rodada
    inteira. Conexão curta é barata; mantê-la viva é cilada.
    """
    fontes = [
        ("sympla", sympla, lambda: sympla.raspar(
            city="brasilia", state="DF", location="Brasília", max_paginas=10)),
        ("ingresse", ingresse, lambda: ingresse.raspar()),
        ("zig", zig, lambda: zig.raspar(estado="DF")),
        ("ticketandgo", ticketandgo,
         lambda: ticketandgo.raspar(locais_df=locais_df or ())),
    ]
    if incluir_shotgun:
        fontes.append(("shotgun", shotgun,
                       lambda: shotgun.raspar(city_slug="brasilia")))
    if apenas:
        fontes = [f for f in fontes if f[0] in apenas]

    resultados = {}
    for nome, modulo, chamada in fontes:
        print(f"\n[{nome}] raspando...")
        iniciada_em = datetime.now(timezone.utc).isoformat()
        try:
            brutos = chamada()
            res = dict(modulo.ULTIMA_RASPAGEM)
        except Exception as e:
            traceback.print_exc()
            brutos, res = None, {"erro": f"{type(e).__name__}: {e}"}
            print(f"[{nome}] FALHOU — seguindo com as outras fontes.")
        con = conexao.conectar()
        try:
            for b in (brutos or ()):
                gravar.gravar(con, nome, b["id_nativo"], "catalogo",
                              b["payload"], iniciada_em, commit=False,
                              **b["extras"])
            con.commit()
            # A coleta é registrada TAMBÉM quando falha: é a linha ausente que
            # protege os eventos da fonte de virarem `sumido` (§8.1, NI-59).
            execucoes.registrar_coleta(
                con, nome, iniciada_em,
                datetime.now(timezone.utc).isoformat(), res)
        finally:
            con.close()
        resultados[nome] = res
    return resultados


def _sumiu(ev, inicio):
    """O evento deixou de aparecer no catálogo na coleta que começou em
    `inicio`? Mesma regra do `tratamento/sumido.py`, aplicada aqui só para não
    gastar requisição de descrição/preço com quem já saiu do ar."""
    if not inicio:
        return False
    visto = tempo.instante(ev["visto_em"])
    return bool(visto and visto < tempo.instante(inicio))


def _fila(con, fontes):
    """A fila dos passos de coleta incremental, lida do `cru`: [(fonte,
    id_nativo, evento normalizado)], já sem os que sumiram do catálogo.

    Lê `cru` + `operacao`, nunca `tratado`. Não é purismo: é o que permite
    descrever e precificar rodarem ANTES de qualquer escrita na prata, que é o
    ponto da fatia 7. E o parser é UM só — o mesmo `tratamento/<fonte>.py` que
    depois vai montar o evento.
    """
    coletas = sumido.ultima_coleta_boa(con)
    saida = []
    for fonte in fontes:
        for id_nativo, ev in comum.normalizados(con, fonte).items():
            if not _sumiu(ev, coletas.get(fonte)):
                saida.append((fonte, id_nativo, ev))
    return saida


def _descrever(con, erros, pausa=0.4):
    """Busca o payload de detalhe dos eventos que ainda não têm e grava na
    camada cru (origem 'detalhe'); quem transforma em descrição/categoria é
    `tratamento/<fonte>.py`.

    INCREMENTAL PELO CRU (§6.4): a fila é "não existe payload 'detalhe' para
    este id". O critério antigo era `descricao IS NULL` na prata, e isso
    re-buscava para sempre os eventos cujo detalhe existe mas veio sem texto —
    eram 11 no Sympla (215 payloads de detalhe para 204 descrições), uma
    requisição desperdiçada por rodada, cada rodada, indefinidamente.

    Shotgun e Ticket and Go já trazem descrição no payload de catálogo (JSON-LD
    / detalhe); Sympla, Ingresse e Zig têm endpoints de evento individual.
    Falha por evento entra em `erros` (vai para execucoes.erros), além do
    contador — padrão sistemático precisa ser visível.
    """
    # URLs do Bileto ficam de fora: o id no fim delas é de outro namespace e o
    # BFF de página devolveria outro evento (NI-17).
    pendentes = [
        (f, i, ev) for f, i, ev in _fila(con, ("sympla", "ingresse", "zig"))
        if "detalhe" not in ev["origens"]
        and not (f == "sympla" and sympla.BILETO_HOST in (ev["url"] or ""))]
    if not pendentes:
        return {"buscadas": 0, "falhas": 0}
    print(f"\n[descrever] {len(pendentes)} eventos sem payload de detalhe...")
    buscadas = falhas = trocados = 0
    for i, (fonte, id_nativo, ev) in enumerate(pendentes, 1):
        evento_id = f"{fonte}:{id_nativo}"
        try:
            if fonte == "sympla":
                id_url = sympla.id_da_url(ev["url"])
                if not id_url:
                    falhas += 1
                    erros.append({"passo": "descrever", "evento_id": evento_id,
                                  "erro": "URL sem id numérico no fim"})
                    continue
                d = sympla.raspar_descricao(id_url)
            else:  # ingresse e zig: slug no fim da URL pública
                slug = ev["url"].rstrip("/").rsplit("/", 1)[-1]
                d = (zig if fonte == "zig" else ingresse).raspar_descricao(slug)
            # Guarda de nome ANTES de gravar (NI-17): payload suspeito não
            # entra nem no cru. O tratamento a repete na leitura (CONFERIR),
            # para um payload de antes da guarda não voltar a poluir a base.
            if d.get("nome") and not texto.mesmo_nome(ev["nome"], d["nome"]):
                trocados += 1
                erros.append({"passo": "descrever", "evento_id": evento_id,
                              "erro": "nome divergente da fonte (id trocado? "
                                      "NI-17) — payload descartado"})
                continue
            gravar.gravar(con, fonte, id_nativo, "detalhe", d["payload"],
                          datetime.now(timezone.utc).isoformat(), commit=False)
            buscadas += 1
        except Exception as e:
            falhas += 1
            erros.append({"passo": "descrever", "evento_id": evento_id,
                          "erro": f"{type(e).__name__}: {e}"})
        if i % 50 == 0:
            print(f"  {i}/{len(pendentes)}...")
        time.sleep(pausa)
    con.commit()
    print(f"  {buscadas} payloads de detalhe gravados | {falhas} falhas"
          + (f" | {trocados} descartados por nome divergente (id trocado?)"
             if trocados else ""))
    return {"buscadas": buscadas, "falhas": falhas, "trocados": trocados}


def _precificar(con, erros, pausa=0.3, tudo=False):
    """Busca o payload de tickets (preço/lotes) de Sympla e Ingresse e grava na
    Bronze (origem='tickets'); quem transforma em preco_min/esgotado é o
    derivar. NÃO é incremental (preço/lote muda entre rodadas), mas refaz só
    os eventos na janela de JANELA_PRECIFICAR_DIAS — quem fica fora mantém o
    último preço derivado até entrar nela (tudo=True cobre todos os futuros).

    Sympla: só eventos com payload de detalhe já guardado — o endpoint de
    tickets não devolve nome para a guarda do NI-17, então o detalhe (que
    passou pela guarda de nome no `_descrever`) é a âncora de que o id não está
    trocado. Zig: lê o __NEXT_DATA__ da página pública (NI-23) e valida o nome
    devolvido. Shotgun não precisa deste passo (as offers já vêm no JSON-LD do
    catálogo).
    """
    agora = datetime.now(timezone.utc)
    limite = agora + timedelta(days=JANELA_PRECIFICAR_DIAS)
    alvos, fora_janela = [], 0
    for fonte, id_nativo, ev in _fila(
            con, ("sympla", "ingresse", "zig", "ticketandgo")):
        dt = tempo.instante(ev["start_date"])
        if not dt or dt < agora:
            continue
        if fonte == "sympla" and ("detalhe" not in ev["origens"]
                                  or not sympla.id_da_url(ev["url"])):
            continue  # sem âncora contra id trocado (NI-17) — fica sem preço
        if not tudo and dt > limite:
            fora_janela += 1  # sem teto silencioso: o log diz quantos ficaram fora
            continue
        alvos.append((fonte, id_nativo, ev))
    if not alvos:
        return {"buscados": 0, "falhas": 0, "fora_janela": fora_janela}
    escopo = ("todos os futuros" if tudo
              else f"próximos {JANELA_PRECIFICAR_DIAS} dias")
    print(f"\n[precificar] tickets de {len(alvos)} eventos ({escopo}, "
          f"Sympla/Ingresse/Zig/Ticket and Go)"
          + (f" — {fora_janela} futuros fora da janela mantêm o último preço"
             if fora_janela else "") + "...")
    buscados = falhas = 0
    for i, (fonte, id_nativo, ev) in enumerate(alvos, 1):
        evento_id = f"{fonte}:{id_nativo}"
        slug = (ev["url"] or "").rstrip("/").rsplit("/", 1)[-1]
        try:
            if fonte == "sympla":
                t = sympla.raspar_tickets(sympla.id_da_url(ev["url"]))
            elif fonte == "zig":  # página pública (slug no fim da URL)
                t = zig.raspar_tickets(slug)
                if not texto.mesmo_nome(ev["nome"], t.get("nome")):
                    falhas += 1
                    erros.append({"passo": "precificar",
                                  "evento_id": evento_id,
                                  "erro": "nome divergente da página — "
                                          "payload descartado"})
                    continue  # payload suspeito não entra nem no cru
            elif fonte == "ticketandgo":  # slug no fim da URL pública
                t = ticketandgo.raspar_tickets(slug)
            else:
                t = ingresse.raspar_tickets(id_nativo)
            gravar.gravar(con, fonte, id_nativo, "tickets", t["payload"],
                          datetime.now(timezone.utc).isoformat(), commit=False)
            buscados += 1
        except Exception as e:
            falhas += 1
            erros.append({"passo": "precificar", "evento_id": evento_id,
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
    con = conexao.conectar()
    try:
        gravar.gravar_cinema_raw(con, r["raw"],
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
    con = conexao.conectar()
    try:
        gravar.gravar_instagram_raw(con, r["raw"],
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
                "FROM cru.instagram p "
                "LEFT JOIN cru.instagram x "
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
            con = conexao.conectar()
            try:
                gravar.gravar_instagram_raw(
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
            "SELECT iniciada_em, fontes FROM operacao.execucoes ORDER BY id DESC"):
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
    rows = con.execute("SELECT fonte, start_date, ruido FROM tratado.eventos").fetchall()
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
            "FROM tratado.eventos GROUP BY fonte ORDER BY fonte"):
        print(f"    {r['fonte']:<9} {r['com']}/{r['tot']}  "
              f"({100 * r['com'] // r['tot']}%)")
    print("  preço mínimo preenchido por fonte (eventos futuros):")
    stats = {}
    for r in con.execute("SELECT fonte, start_date, preco_min FROM tratado.eventos"):
        dt = tempo.instante(r["start_date"])
        if not dt or dt < agora:
            continue
        com, tot = stats.get(r["fonte"], (0, 0))
        stats[r["fonte"]] = (com + (r["preco_min"] is not None), tot + 1)
    for fonte in sorted(stats):
        com, tot = stats[fonte]
        print(f"    {fonte:<9} {com}/{tot}  ({100 * com // tot}%)")

    # --- camada Bronze: payloads brutos e colunas derivadas ---
    # cru.inventario reúne as CONTAGENS das oito tabelas de bruto (não os
    # payloads). `versoes` > `registros` é o append-only funcionando: são as
    # versões guardadas de cada chave ao longo do tempo.
    raws = con.execute("SELECT fonte, origem, versoes, registros "
                       "FROM cru.inventario WHERE registros > 0 "
                       "ORDER BY fonte, origem").fetchall()
    print("  camada cru (registros → versões guardadas):")
    for r in raws:
        print(f"    {r['fonte']:<12} {r['origem']:<14} {r['registros']:>5}"
              f" → {r['versoes']}")
    if derivado is not None:
        derivado = dict(derivado)
        lotes_n = derivado.pop("lotes", 0)
        rejeitados = derivado.pop("rejeitados", [])
        print("  colunas reconstruídas do cru: " +
              ", ".join(f"{c}: {n} eventos" for c, n in derivado.items()))
        print(f"  lotes de ingresso (tabela lotes): {lotes_n}")
        if rejeitados:
            print(f"  *** {len(rejeitados)} payload(s) REPROVADOS pela guarda "
                  "(era de API antiga? id trocado?) — não viraram evento:")
            for r in rejeitados[:10]:
                print(f"      {r['evento_id']}: {r['erro']}")

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
                  "--rodada-local` (a visão exige a assinatura; a mesma "
                  "rodada traz o Shotgun, que o CI não lê)")

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
    chave = conexao.env_var("TMDB_API_KEY")
    if not chave:
        print("\n[tmdb] TMDB_API_KEY ausente — filmes seguem sem sinopse/nota.")
        return None
    pendentes = con.execute(
        "SELECT f.id, f.titulo, f.titulo_original FROM tratado.filmes f "
        "LEFT JOIN cru.tmdb x ON x.filme_id = f.id "
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
        gravar.gravar_tmdb(con, f["id"], payload, agora)
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
    if not midias.token():
        print("\n[poster] BLOB_READ_WRITE_TOKEN ausente — hotlink mantido.")
        return None
    pendentes = con.execute(
        "SELECT f.id, f.poster FROM tratado.filmes f "
        "LEFT JOIN operacao.midias m "
        "  ON m.chave = f.id AND m.tipo = 'poster' "
        "WHERE f.poster IS NOT NULL AND m.chave IS NULL "
        "ORDER BY f.id").fetchall()
    if not pendentes:
        return 0
    print(f"\n[poster] copiando {len(pendentes)} pôster(es) para o storage...")
    agora = datetime.now(timezone.utc).isoformat()
    n = 0
    for f in pendentes:
        try:
            dados, ctype = midias.baixar(f["poster"])
            ext = midias.EXTENSOES.get(ctype, "jpg")
            url = midias.subir(dados, f"posters/{f['id']}.{ext}", ctype)
        except Exception as e:
            erros.append({"passo": "poster", "evento_id": f["id"],
                          "erro": f"{type(e).__name__}: {e}"})
            continue
        gravar.gravar_midia(con, f["id"], "poster", url, agora)
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
    if not midias.token():
        return None
    pendentes = con.execute(
        "SELECT p.perfil, p.code FROM cru.instagram p "
        "LEFT JOIN operacao.midias m "
        "  ON m.chave = p.code AND m.tipo = 'flyer' "
        "WHERE p.origem = 'post' AND m.chave IS NULL "
        "ORDER BY p.code").fetchall()
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
            url = midias.subir(arq.read_bytes(),
                              f"instagram/{r['code']}{arq.suffix.lower()}", ctype)
        except Exception as e:
            erros.append({"passo": "midia-instagram", "evento_id": r["code"],
                          "erro": f"{type(e).__name__}: {e}"})
            continue
        gravar.gravar_midia(con, r["code"], "flyer", url, agora)
        n += 1
    if n:
        print(f"\n[midia] {n} flyer(s) do Instagram no storage próprio")
    return n


def main():
    inicio = time.monotonic()
    iniciada_em = datetime.now(timezone.utc).isoformat()
    so_enriquecer = "--so-enriquecer" in sys.argv
    so_derivar = "--so-derivar" in sys.argv
    # --rodada-local: o que o CI NÃO consegue fazer. Nasceu como
    # --so-instagram (a extração de flyer exige a assinatura do Claude) e em
    # 2026-07-28 ganhou o Shotgun, que o runner do Actions não consegue ler
    # (NI-58). O nome antigo continua valendo — está em doc, hábito e no aviso
    # que o próprio relatório do cron imprime.
    rodada_local = ("--rodada-local" in sys.argv or "--so-instagram" in sys.argv)
    sem_shotgun = "--sem-shotgun" in sys.argv
    sem_cinema = "--sem-cinema" in sys.argv
    sem_instagram = "--sem-instagram" in sys.argv
    sem_extracao = "--sem-extracao-flyer" in sys.argv
    modo = ("so-enriquecer" if so_enriquecer else "so-derivar" if so_derivar
            else "rodada-local" if rodada_local
            else "cron" if sem_extracao
            else "sem-shotgun" if sem_shotgun else "completo")

    # Conexões CURTAS por bloco (2026-07-27, a pedido do autor): o pipeline
    # intercala minutos de raspagem/visão com escrita na base, e conexão
    # parada é derrubada pela rede em silêncio (SSL closed no meio da rodada,
    # visto no Zig). Cada bloco abre a sua e fecha; os passos de raspagem
    # abrem as próprias depois da rede. Alongar a vida da conexão é cilada.
    # Único ponto do pipeline que aplica DDL (conectar() não aplica por padrão
    # desde 2026-07-28 — spec 20260728_arquitetura-medalhao, D9). As conexões
    # seguintes só leem e escrevem dado.
    con = conexao.conectar(aplicar_schema=True)
    _checar_schema(con)
    # A referência canônica de casas do DF, lida ANTES da raspagem: o filtro
    # `_do_df` do Ticket and Go depende dela, e o coletor não conhece a base.
    locais_df = curadoria.nomes_df(con)
    con.close()

    resultados, erros = {}, []
    desc = prec = None
    if not (so_enriquecer or so_derivar):
        # --rodada-local: rodada curta com o que só a máquina do autor faz.
        # (a) o Shotgun, que devolve 0 no runner do Actions e vai bem aqui
        #     (NI-58) — sem descrever/precificar, que ele não usa: o JSON-LD
        #     do catálogo já traz descrição, line-up e preço;
        # (b) a fila de extração de flyer deixada pelo cron (que roda com
        #     --sem-extracao-flyer, porque a visão exige a assinatura).
        # Re-raspa os perfis de propósito — a URL de mídia do CDN expira em
        # horas, então a Bronze precisa estar fresca para a visão baixar.
        if rodada_local:
            if not sem_shotgun:
                resultados = _raspar(apenas=["shotgun"])
        else:
            resultados = _raspar(incluir_shotgun=not sem_shotgun,
                                 locais_df=locais_df)
            if resultados and all("erro" in r for r in resultados.values()):
                sys.exit("Todas as fontes falharam — base não atualizada.")
            # descrever/precificar leem a fila do cru (não da prata, que ainda
            # não foi reconstruída nesta rodada) e escrevem no cru. Tocam a base
            # a cada evento — os gaps são curtos, uma conexão para o bloco basta.
            con = conexao.conectar()
            desc = _descrever(con, erros)
            prec = _precificar(con, erros,
                               tudo="--precificar-tudo" in sys.argv)
            con.close()
            if not sem_cinema:
                resultados["cinema"] = _raspar_cinema(erros)
        if not sem_instagram:
            r_insta = _raspar_instagram(erros, extrair=not sem_extracao)
            if r_insta is not None:
                resultados["instagram"] = r_insta
            # O flyer sobe para o storage próprio ANTES do tratamento, porque é
            # a derivação que grava a URL em eventos.imagem. Lê cru+operacao,
            # escreve em operacao — nada de `tratado`.
            con = conexao.conectar()
            _subir_midias_instagram(con, erros)
            con.close()

    # daqui em diante é tratamento/relatório: conexão nova — a raspagem acima
    # pode ter levado muitos minutos.
    con = conexao.conectar()

    # O ciclo inteiro do tratamento, numa transação só: enquanto ele reconstrói
    # `tratado`, o site e o MCP seguem lendo `public` (§8.1).
    saida = ciclo.executar(con, so_enriquecer=so_enriquecer)

    # TMDB e cópia de pôster DEPOIS do tratamento: a lista do que está em cartaz
    # É a tabela `tratado.filmes`, então não há como montá-la antes. Os dois
    # escrevem em `cru.tmdb` e `operacao.midias`; se trouxeram algo, o ciclo roda
    # de novo para aplicar (é idempotente e custa segundos).
    if (not (so_enriquecer or so_derivar or rodada_local)
            and not sem_cinema and "--sem-tmdb" not in sys.argv):
        novos = _enriquecer_cinema(con, erros) or 0
        novos += _copiar_posters(con, erros) or 0
        if novos:
            saida = ciclo.executar(con, so_enriquecer=so_enriquecer)

    cur = saida["curadoria"]
    if cur["aplicadas"] or cur["orfas"]:
        print(f"\n[curadoria] {cur['aplicadas']} correções reaplicadas"
              + (f" | {cur['orfas']} órfãs (registro sumiu da prata — "
                 f"aparecem em curado.pendencias)" if cur["orfas"] else ""))
    # Única exceção ao "nada é apagado" no cru, e só de versão INTERMEDIÁRIA
    # antiga: a mais recente de cada chave nunca tem sibling mais nova, então
    # nunca casa a condição. Não roda em --so-enriquecer (não houve coleta).
    if not so_enriquecer:
        podados = gravar.podar_historico(con, JANELA_HISTORICO_DIAS)
        if podados:
            print(f"\n[cru] histórico podado (> {JANELA_HISTORICO_DIAS} dias): "
                  + ", ".join(f"{f}: {n}" for f, n in podados.items()))
    duracao = time.monotonic() - inicio
    derivado, enriq = saida["derivado"], saida["enriquecimento"]
    sumidos = saida["sumidos"]
    if derivado and derivado["rejeitados"]:
        # Payload que a guarda do §6.3 reprovou. Nunca é silêncio: o evento
        # simplesmente não estaria na base, e ninguém saberia por quê.
        erros.extend({"passo": "tratar", **r} for r in derivado["rejeitados"])
    # O relatório lê execucoes ANTES do registro: a comparação é com a rodada
    # anterior de verdade, não com esta.
    _relatorio(con, resultados, derivado, saida["cinema"], saida["instagram"],
               enriq, sumidos, duracao)
    execucoes.registrar_execucao(
        con, iniciada_em, round(duracao, 1), modo, resultados,
        {"descrever": desc, "precificar": prec, "derivado": derivado,
         "cinema": saida["cinema"], "instagram": saida["instagram"],
         "ruido": len(enriq["ruido"]), "dedupe_grupos": len(enriq["grupos"]),
         "sumidos": len(sumidos) if sumidos is not None else None},
        erros)
    con.close()


if __name__ == "__main__":
    main()
