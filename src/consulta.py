"""Camada de consulta da base unificada de eventos.

Contrato pensado para virar uma tool MCP: uma unica funcao parametrizada,
todos os argumentos opcionais, retorno em lista de dicts (JSON-serializavel).

Pegadinha das datas em formatos mistos (Sympla/Ingresse "+00:00", Shotgun
".000Z"): desde a Fase 0b quem resolve e o store.upsert_eventos, que normaliza
tudo para ISO UTC na escrita (invariante do schema). Aqui basta normalizar os
PARAMETROS (tempo.norm_ts) — a comparacao no SQL volta a ser lexical, segura.
"""

from datetime import datetime, timezone

import store
import tempo

# Campos uteis expostos ao agente (subconjunto enxuto da tabela).
# `id` (<fonte>:<id_nativo>) entrou em 2026-07-26: o site publico precisa de
# endereco proprio por evento (uma pagina por evento e o que a Fase 2 marca em
# JSON-LD) e a url da fonte nao serve de identificador de rota. Serve ao agente
# tambem — detalhar_evento aceita id ou url.
# preco_min = menor lote PAGO em R$ (total, com taxa); tem_gratis 1 = ha lote
# gratis nao esgotado (com preco_min NULL = evento gratis); esgotado 1 = sem
# ingressos; bairro/popularidade derivados da camada Bronze (specs camada-prata
# e lotes-ingressos).
CAMPOS = ["id", "nome", "fonte", "start_date", "end_date", "cidade", "estado",
          "local_nome", "endereco", "bairro", "categoria", "organizador",
          "url", "imagem", "atracoes", "preco_min", "tem_gratis", "esgotado",
          "popularidade"]

# A descricao completa de dezenas de eventos e peso morto no contexto do agente;
# um trecho basta para ele entender o estilo do evento (o texto inteiro fica na
# base, indexado pelo FTS).
DESCRICAO_MAX = 300


def buscar_eventos(texto=None, cidade=None, data_inicio=None, data_fim=None,
                   limite=20, incluir_ruido=False):
    """Busca eventos na base unificada.

    Por padrao esconde o que o enriquecimento v1 marcou — eventos com ruido=1
    (anuncio/curso) e membros nao-canonicos de grupos de dedupe cross-fonte —
    e tambem eventos cancelados na origem (cancelado=1, derivado da Bronze) e
    sumidos do catalogo da fonte (sumido=1, provavel remocao silenciosa).
    Esgotado NAO some: "esta esgotado" e resposta util (campo `esgotado`).
    O canonico de um grupo carrega em `outras_urls` os links dos membros
    colapsados (o mesmo evento nas outras plataformas).

    Args:
        texto: busca textual sobre nome/categoria/atracoes/descricao. Sintaxe
            websearch do Postgres (ex.: "funk OR techno", frase entre aspas,
            -termo exclui). Omitido = sem filtro de texto.
        cidade: filtro exato por cidade.
        data_inicio: limite inferior (ISO) sobre start_date, inclusivo.
        data_fim: limite superior (ISO) sobre start_date, inclusivo.
        limite: numero maximo de resultados (ordenados por start_date).
        incluir_ruido: True devolve tambem os marcados como ruido, os
            cancelados e os sumidos (depuracao; nao exposto na tool MCP).

    Returns:
        Lista de dicts (nunca sqlite3.Row), ordenada por start_date.
    """
    con = store.conectar()

    where, params = [], []
    if not incluir_ruido:
        where.append("e.ruido = 0")
        where.append("(e.cancelado IS NULL OR e.cancelado = 0)")
        where.append("e.sumido = 0")
    # Duplicata cross-fonte: so o canonico responde pelo grupo.
    where.append("e.dedupe_canonico = 1")
    if texto:
        where.append("e.busca @@ websearch_to_tsquery('pt', %s)")
        params.append(texto)
    if cidade:
        where.append("e.cidade = %s")
        params.append(cidade)
    # Parametro de data normalizado como a coluna (invariante do schema);
    # valor que nao parseia vira NULL e a comparacao nao devolve nada.
    if data_inicio:
        where.append("e.start_date >= %s")
        params.append(tempo.norm_ts(data_inicio))
    if data_fim:
        where.append("e.start_date <= %s")
        params.append(tempo.norm_ts(data_fim))

    # outras_urls: links do mesmo evento nas outras plataformas (NULL sem grupo).
    outras = ("(SELECT string_agg(o.url, ',') FROM eventos o "
              "WHERE o.dedupe_grupo = e.dedupe_grupo AND o.id != e.id) "
              "AS outras_urls")
    descr = f"substr(e.descricao, 1, {DESCRICAO_MAX}) AS descricao"
    sql = f"SELECT {', '.join(CAMPOS)}, {descr}, {outras} FROM eventos e"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.start_date LIMIT %s"
    params.append(limite)

    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def detalhar_evento(url):
    """Devolve UM evento completo: os mesmos campos da busca, a descricao
    INTEIRA (sem o corte de DESCRICAO_MAX) e a lista de lotes de ingresso com
    o nome cru da fonte (a condicao do lote — "CORTESIA FEMININA ATE 00H",
    "meia-entrada" — esta no nome, de proposito; spec 20260710_lotes-ingressos).

    Lookup pela url exata que buscar_eventos devolveu (em url ou outras_urls).
    Se a url for de um membro nao-canonico de grupo de dedupe, responde o
    canonico. Nao achou -> {"erro": ...}.

    Aceita tambem o ID interno (`<fonte>:<id_nativo>`) no lugar da url — o
    site publico precisa de endereco proprio por evento (uma pagina por
    evento e o que a Fase 2 marca em JSON-LD), e a url da fonte nao serve de
    identificador de rota. A tool MCP continua passando url; quem chama com
    id e a API do site.
    """
    con = store.conectar()
    alvo = (url or "").strip()
    coluna = "url" if alvo.startswith("http") else "id"
    row = con.execute(f"SELECT id, dedupe_grupo, dedupe_canonico FROM eventos "
                      f"WHERE {coluna} = %s", (alvo,)).fetchone()
    if row and not row["dedupe_canonico"] and row["dedupe_grupo"]:
        row = con.execute(
            "SELECT id FROM eventos WHERE dedupe_grupo = %s "
            "AND dedupe_canonico = 1", (row["dedupe_grupo"],)).fetchone() or row
    if not row:
        con.close()
        return {"erro": f"nenhum evento na base com a url {url!r} — use a url "
                        "exata devolvida por buscar_eventos"}
    outras = ("(SELECT string_agg(o.url, ',') FROM eventos o "
              "WHERE o.dedupe_grupo = e.dedupe_grupo AND o.id != e.id) "
              "AS outras_urls")
    ev = dict(con.execute(
        f"SELECT {', '.join(CAMPOS)}, e.descricao, {outras} "
        "FROM eventos e WHERE e.id = %s", (row["id"],)).fetchone())
    ev["lotes"] = [dict(r) for r in con.execute(
        "SELECT nome, preco, taxa, gratis, esgotado FROM lotes "
        "WHERE evento_id = %s ORDER BY ordem", (row["id"],))]
    con.close()
    return ev


# ── Domínio cinema (NI-07, spec 20260711_raspagem-cinema) ──────────────────

# Campos de filmes expostos ao agente. `poster` entrou na lista com o rework
# da página de cinema (NI-35 — o card do site precisa dele) e sinopse/ano/
# nota/votos com o NI-36 (TMDB); poster_proprio é a cópia no storage (NI-37,
# o front prefere quando existe); tmdb_id permite linkar a página do filme no
# TMDB (atribuição exigida pelos ToS deles). `trailer` segue só no
# sessoes_filme.
CAMPOS_FILME = ["id", "titulo", "titulo_original", "generos", "duracao_min",
                "classificacao", "distribuidora", "url", "poster",
                "poster_proprio", "em_pre_venda", "sinopse", "ano", "nota",
                "votos", "tmdb_id"]

# A hora exibida/filtrada é SEMPRE a de Brasília; `sessoes.inicio` é UTC
# (invariante do schema), então o filtro de horário converte na query.
_TZ_BSB = "America/Sao_Paulo"


def _lista(v):
    """Normaliza um filtro múltiplo: None/''→[], 'a,b'→['a','b'], lista→lista.

    Aceitar CSV além de lista deixa a api/dados.py repassar a querystring
    sem parse próprio (a regra de "sem lógica na API" vale até para vírgula).
    """
    if not v:
        return []
    if isinstance(v, str):
        v = v.split(",")
    return [s.strip() for s in v if s and s.strip()]


def _filtro_hora(where, params, hora_de, hora_ate, col="s.inicio"):
    """Janela de HORA LOCAL de Brasília sobre uma coluna UTC (`ate` exclusivo);
    de > ate vira janela que cruza a meia-noite. Compartilhado por
    buscar_filmes e sessoes_filme — a regra tem que ser uma só."""
    hora_sql = f"EXTRACT(HOUR FROM ({col}::timestamptz AT TIME ZONE '{_TZ_BSB}'))"
    if hora_de is not None and hora_ate is not None and hora_de > hora_ate:
        where.append(f"({hora_sql} >= %s OR {hora_sql} < %s)")
        params.extend([hora_de, hora_ate])
    else:
        if hora_de is not None:
            where.append(f"{hora_sql} >= %s")
            params.append(hora_de)
        if hora_ate is not None:
            where.append(f"{hora_sql} < %s")
            params.append(hora_ate)


def _filtro_cinemas(where, params, cinema, col="s.cinema"):
    """Um ou mais cinemas (parcial, sem caixa), OR entre eles."""
    cinemas = _lista(cinema)
    if cinemas:
        where.append("(" + " OR ".join([f"{col} ILIKE %s"] * len(cinemas)) + ")")
        params.extend(f"%{c}%" for c in cinemas)


def buscar_filmes(texto=None, data_inicio=None, data_fim=None, cinema=None,
                  generos=None, classificacao=None, hora_de=None,
                  hora_ate=None, limite=20):
    """Filmes em cartaz nos cinemas-alvo de Brasília, agregados por filme.

    Sessões passadas não contam: sem data_inicio, a janela começa AGORA.
    Ordena por nº de sessões na janela (mais em cartaz primeiro) — o agente
    reordena como quiser.

    Args:
        texto: busca textual sobre título e gêneros (websearch, ex.:
            "animação", "terror OR suspense"). Omitido = todos em cartaz.
        data_inicio: limite inferior (ISO) sobre o início da sessão; default agora.
        data_fim: limite superior (ISO), inclusivo.
        cinema: um ou mais cinemas (string parcial sem caixa, CSV ou lista:
            "pier", "kinoplex", "Cine Brasília,Cine Cultura" — OR entre eles).
        generos: um ou mais gêneros (CSV ou lista; casa por substring no CSV
            da fonte, OR entre eles: "Terror,Suspense").
        classificacao: uma ou mais classificações indicativas, texto EXATO da
            fonte ("Livre", "6 anos" — os valores estão em facetas_filmes()).
        hora_de/hora_ate: janela da HORA LOCAL de Brasília do início da sessão
            (ints 0–23; `ate` exclusivo). hora_de > hora_ate vira janela que
            cruza a meia-noite (ex.: 22→6 = sessão coruja).
        limite: máximo de filmes.

    Returns:
        Lista de dicts: campos do filme + sessoes (contagem na janela),
        cinemas (nomes, ordenados), primeira_sessao/ultima_sessao (ISO UTC).
    """
    con = store.conectar()
    where = ["s.inicio >= %s"]
    params = [tempo.norm_ts(data_inicio)
              or datetime.now(timezone.utc).isoformat()]
    if data_fim:
        where.append("s.inicio <= %s")
        params.append(tempo.norm_ts(data_fim))
    if texto:
        where.append("f.busca @@ websearch_to_tsquery('pt', %s)")
        params.append(texto)
    _filtro_cinemas(where, params, cinema)
    gens = _lista(generos)
    if gens:
        where.append("(" + " OR ".join(["f.generos ILIKE %s"] * len(gens)) + ")")
        params.extend(f"%{g}%" for g in gens)
    classes = _lista(classificacao)
    if classes:
        where.append("f.classificacao = ANY(%s)")
        params.append(classes)
    _filtro_hora(where, params, hora_de, hora_ate)
    campos = ", ".join(f"f.{c}" for c in CAMPOS_FILME)
    rows = con.execute(
        f"SELECT {campos}, COUNT(s.id) AS sessoes, "
        "string_agg(DISTINCT s.cinema, ', ' ORDER BY s.cinema) AS cinemas, "
        "MIN(s.inicio) AS primeira_sessao, MAX(s.inicio) AS ultima_sessao "
        "FROM filmes f JOIN sessoes s ON s.filme_id = f.id "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY {campos} ORDER BY COUNT(s.id) DESC, f.titulo LIMIT %s",
        [*params, limite]).fetchall()
    con.close()
    return [dict(r) for r in rows]


def facetas_filmes():
    """Valores distintos dos filtros da página de cinema (NI-35), calculados
    só sobre o que tem sessão FUTURA — faceta de filme que saiu de cartaz é
    opção que devolve vazio.

    Returns:
        {"generos": [...], "classificacoes": [...], "cinemas": [...]} —
        gêneros desmembrados do CSV da fonte, classificações no texto exato
        (ordenadas Livre→18), cinemas pelos apelidos canônicos.
    """
    con = store.conectar()
    agora = datetime.now(timezone.utc).isoformat()
    rows = con.execute(
        "SELECT DISTINCT f.generos, f.classificacao "
        "FROM filmes f JOIN sessoes s ON s.filme_id = f.id "
        "WHERE s.inicio >= %s", (agora,)).fetchall()
    generos, classes = set(), set()
    for r in rows:
        generos.update(g.strip() for g in (r["generos"] or "").split(",")
                       if g.strip())
        if r["classificacao"]:
            classes.add(r["classificacao"])
    cinemas = [r["cinema"] for r in con.execute(
        "SELECT DISTINCT cinema FROM sessoes WHERE inicio >= %s "
        "ORDER BY cinema", (agora,))]
    # dias LOCAIS com sessão futura — é o que o calendário do site habilita
    # (a grade real cobre ~8 dias; o resto do mês fica desabilitado)
    dias = [r["dia"] for r in con.execute(
        "SELECT DISTINCT to_char(inicio::timestamptz AT TIME ZONE "
        f"'{_TZ_BSB}', 'YYYY-MM-DD') AS dia "
        "FROM sessoes WHERE inicio >= %s ORDER BY dia", (agora,))]
    con.close()

    def _ordem_classe(c):
        # "Livre" antes de tudo; o resto pelo número ("6 anos", "12 anos"...)
        digitos = "".join(ch for ch in c if ch.isdigit())
        return (0, 0) if not digitos else (1, int(digitos))
    return {"generos": sorted(generos),
            "classificacoes": sorted(classes, key=_ordem_classe),
            "cinemas": cinemas, "dias": dias}


def sessoes_filme(filme, data_inicio=None, data_fim=None, cinema=None,
                  hora_de=None, hora_ate=None):
    """Sessões detalhadas de UM filme (horário, cinema, sala, tipos, preço,
    link de compra) — o análogo do detalhar_evento para o cinema.

    `filme` é o id ou o título (busca parcial, sem caixa/acento via ILIKE +
    unaccent); com mais de um candidato, responde o com mais sessões futuras.
    Mesma janela default da busca: sessões passadas ficam de fora.
    `cinema` (parcial, CSV/lista) e `hora_de`/`hora_ate` (hora LOCAL, `ate`
    exclusivo) filtram as sessões — mesmos filtros da busca, para achar o
    lugar/horário certo de ver ESTE filme. `cinemas` no retorno lista onde o
    filme passa SEM o filtro aplicado (são as opções do filtro, não o
    resultado dele).
    """
    con = store.conectar()
    alvo = (filme or "").strip()
    agora = datetime.now(timezone.utc).isoformat()
    row = con.execute("SELECT id FROM filmes WHERE id = %s",
                      (alvo,)).fetchone()
    if not row and alvo:
        # título parcial, sem caixa/acento; empate vai para quem tem mais
        # sessões futuras (o "em cartaz de verdade")
        row = con.execute(
            "SELECT f.id FROM filmes f "
            "LEFT JOIN sessoes s ON s.filme_id = f.id AND s.inicio >= %s "
            "WHERE unaccent(f.titulo) ILIKE unaccent(%s) "
            "GROUP BY f.id ORDER BY COUNT(s.id) DESC LIMIT 1",
            (agora, f"%{alvo}%")).fetchone()
    if not row:
        con.close()
        return {"erro": f"nenhum filme em cartaz casando com {filme!r} — use "
                        "o id ou título devolvido por buscar_filmes"}
    campos = ", ".join(CAMPOS_FILME + ["trailer"])
    f = dict(con.execute(f"SELECT {campos} FROM filmes WHERE id = %s",
                         (row["id"],)).fetchone())
    inicio_janela = tempo.norm_ts(data_inicio) or agora
    f["cinemas"] = [r["cinema"] for r in con.execute(
        "SELECT DISTINCT cinema FROM sessoes "
        "WHERE filme_id = %s AND inicio >= %s ORDER BY cinema",
        (row["id"], inicio_janela))]
    where = ["filme_id = %s", "inicio >= %s"]
    params = [row["id"], inicio_janela]
    if data_fim:
        where.append("inicio <= %s")
        params.append(tempo.norm_ts(data_fim))
    _filtro_cinemas(where, params, cinema, col="cinema")
    _filtro_hora(where, params, hora_de, hora_ate, col="inicio")
    f["sessoes"] = [dict(r) for r in con.execute(
        "SELECT cinema, inicio, sala, tipos, preco, url_compra FROM sessoes "
        f"WHERE {' AND '.join(where)} ORDER BY inicio, cinema", params)]
    con.close()
    return f


def procedencia():
    """Quando cada fonte foi coletada pela última vez, e quanto ela responde
    hoje na base.

    Existe porque o site precisa mostrar a idade do dado (spec
    20260726_abrir-ao-publico §3 passo 3): enquanto a raspagem não for
    comprovadamente diária, esconder que o dado é de três dias atrás é o pior
    modo de falha do produto — resposta errada com cara de certa.

    `raspado_em` é a âncora certa: só o upsert do catálogo o atualiza (os
    passos descrever/precificar mexem em outras colunas), então ele responde
    "quando esta fonte foi vista viva pela última vez".

    Returns:
        Lista de dicts {fonte, ultima_coleta (ISO UTC), eventos, futuros},
        da fonte mais recente para a mais velha.
    """
    con = store.conectar()
    agora = datetime.now(timezone.utc).isoformat()
    rows = con.execute(
        "SELECT fonte, MAX(raspado_em) AS ultima_coleta, "
        "       COUNT(*) AS eventos, "
        "       COUNT(*) FILTER (WHERE start_date >= %s AND ruido = 0 "
        "                        AND sumido = 0 "
        "                        AND (cancelado IS NULL OR cancelado = 0)) "
        "         AS futuros "
        "FROM eventos GROUP BY fonte ORDER BY MAX(raspado_em) DESC",
        (agora,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _mostrar(titulo, eventos):
    print(f"\n### {titulo}  ({len(eventos)} resultados)")
    if not eventos:
        print("  (nenhum)")
        return
    for e in eventos:
        quando = (e["start_date"] or "")[:16].replace("T", " ")
        print(f"  - {quando} | [{e['fonte']}] {(e['nome'] or '')[:55]}")
        print(f"      {e['local_nome'] or '?'} - {e['cidade'] or '?'} | {e['url']}")


if __name__ == "__main__":
    agora = datetime.now(timezone.utc).isoformat()

    # 1) "pagode" em Brasilia, a partir de agora.
    _mostrar('"pagode" em Brasilia (futuros)',
             buscar_eventos(texto="pagode", cidade="Brasília",
                            data_inicio=agora))

    # 2) proximos eventos sem filtro de texto -- checa as 3 fontes e que nada
    #    passado vaza.
    proximos = buscar_eventos(cidade="Brasília", data_inicio=agora, limite=50)
    _mostrar("Proximos eventos (sem texto, so futuros)", proximos[:8])
    fontes = sorted({e["fonte"] for e in proximos})
    passados = [e for e in proximos
                if tempo.norm_ts(e["start_date"])
                and tempo.norm_ts(e["start_date"]) < agora]
    print(f"    fontes presentes: {fontes} | eventos passados que vazaram: {len(passados)}")

    # 3) um genero (funk OR techno).
    _mostrar('"funk OR techno" (futuros)',
             buscar_eventos(texto="funk OR techno", cidade="Brasília",
                            data_inicio=agora))

    # 4) caso que deve retornar vazio.
    _mostrar("Texto sem correspondencia (deve vir vazio)",
             buscar_eventos(texto="xyzzyabracadabra123"))
