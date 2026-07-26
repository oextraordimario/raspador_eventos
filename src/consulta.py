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
# preco_min = menor lote PAGO em R$ (total, com taxa); tem_gratis 1 = ha lote
# gratis nao esgotado (com preco_min NULL = evento gratis); esgotado 1 = sem
# ingressos; bairro/popularidade derivados da camada Bronze (specs camada-prata
# e lotes-ingressos).
CAMPOS = ["nome", "fonte", "start_date", "end_date", "cidade", "estado",
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
    """
    con = store.conectar()
    row = con.execute("SELECT id, dedupe_grupo, dedupe_canonico FROM eventos "
                      "WHERE url = %s", ((url or "").strip(),)).fetchone()
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

# Campos de filmes expostos ao agente (poster/trailer ficam de fora da lista:
# peso morto em dezenas de resultados; sessoes_filme os devolve).
CAMPOS_FILME = ["id", "titulo", "generos", "duracao_min", "classificacao",
                "distribuidora", "url", "em_pre_venda"]


def buscar_filmes(texto=None, data_inicio=None, data_fim=None, cinema=None,
                  limite=20):
    """Filmes em cartaz nos cinemas-alvo de Brasília, agregados por filme.

    Sessões passadas não contam: sem data_inicio, a janela começa AGORA.
    Ordena por nº de sessões na janela (mais em cartaz primeiro) — o agente
    reordena como quiser.

    Args:
        texto: busca textual sobre título e gêneros (websearch, ex.:
            "animação", "terror OR suspense"). Omitido = todos em cartaz.
        data_inicio: limite inferior (ISO) sobre o início da sessão; default agora.
        data_fim: limite superior (ISO), inclusivo.
        cinema: filtro por nome do cinema (parcial, sem caixa: "pier", "kinoplex").
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
    if cinema:
        where.append("s.cinema ILIKE %s")
        params.append(f"%{cinema}%")
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


def sessoes_filme(filme, data_inicio=None, data_fim=None, cinema=None):
    """Sessões detalhadas de UM filme (horário, cinema, sala, tipos, preço,
    link de compra) — o análogo do detalhar_evento para o cinema.

    `filme` é o id ou o título (busca parcial, sem caixa/acento via ILIKE +
    unaccent); com mais de um candidato, responde o com mais sessões futuras.
    Mesma janela default da busca: sessões passadas ficam de fora.
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
    campos = ", ".join(CAMPOS_FILME + ["poster", "trailer"])
    f = dict(con.execute(f"SELECT {campos} FROM filmes WHERE id = %s",
                         (row["id"],)).fetchone())
    where = ["filme_id = %s", "inicio >= %s"]
    params = [row["id"], tempo.norm_ts(data_inicio) or agora]
    if data_fim:
        where.append("inicio <= %s")
        params.append(tempo.norm_ts(data_fim))
    if cinema:
        where.append("cinema ILIKE %s")
        params.append(f"%{cinema}%")
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
