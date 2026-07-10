"""Camada de consulta da base unificada de eventos.

Contrato pensado para virar uma tool MCP: uma unica funcao parametrizada,
todos os argumentos opcionais, retorno em lista de dicts (JSON-serializavel).

Pegadinha tratada aqui: as fontes gravam datas ISO em formatos diferentes
(Sympla/Ingresse usam "+00:00", Shotgun usa ".000Z"). A comparacao lexical
de strings falha entre esses formatos -- por exemplo, um evento Shotgun no
mesmo instante que um limite superior "+00:00" seria excluido por engano.
Por isso toda data passa por tempo.norm_ts (registrada como funcao SQL)
antes de comparar/ordenar.
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
        texto: busca textual (FTS) sobre nome/categoria. Aceita a sintaxe do
            FTS5 (ex.: "funk OR techno"). Omitido = sem filtro de texto.
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
    # Funcao SQL para comparar datas normalizadas (contorna os formatos mistos).
    con.create_function("norm_ts", 1, tempo.norm_ts, deterministic=True)

    where, params = [], []
    if not incluir_ruido:
        where.append("e.ruido = 0")
        where.append("(e.cancelado IS NULL OR e.cancelado = 0)")
        where.append("e.sumido = 0")
    # Duplicata cross-fonte: so o canonico responde pelo grupo.
    where.append("e.dedupe_canonico = 1")
    if texto:
        where.append("e.rowid IN (SELECT rowid FROM eventos_fts "
                     "WHERE eventos_fts MATCH ?)")
        params.append(texto)
    if cidade:
        where.append("e.cidade = ?")
        params.append(cidade)
    if data_inicio:
        where.append("norm_ts(e.start_date) >= norm_ts(?)")
        params.append(data_inicio)
    if data_fim:
        where.append("norm_ts(e.start_date) <= norm_ts(?)")
        params.append(data_fim)

    # outras_urls: links do mesmo evento nas outras plataformas (NULL sem grupo).
    outras = ("(SELECT GROUP_CONCAT(o.url) FROM eventos o "
              "WHERE o.dedupe_grupo = e.dedupe_grupo AND o.id != e.id) "
              "AS outras_urls")
    descr = f"substr(e.descricao, 1, {DESCRICAO_MAX}) AS descricao"
    sql = f"SELECT {', '.join(CAMPOS)}, {descr}, {outras} FROM eventos e"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY norm_ts(e.start_date) LIMIT ?"
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
                      "WHERE url = ?", ((url or "").strip(),)).fetchone()
    if row and not row["dedupe_canonico"] and row["dedupe_grupo"]:
        row = con.execute(
            "SELECT id FROM eventos WHERE dedupe_grupo = ? "
            "AND dedupe_canonico = 1", (row["dedupe_grupo"],)).fetchone() or row
    if not row:
        con.close()
        return {"erro": f"nenhum evento na base com a url {url!r} — use a url "
                        "exata devolvida por buscar_eventos"}
    outras = ("(SELECT GROUP_CONCAT(o.url) FROM eventos o "
              "WHERE o.dedupe_grupo = e.dedupe_grupo AND o.id != e.id) "
              "AS outras_urls")
    ev = dict(con.execute(
        f"SELECT {', '.join(CAMPOS)}, e.descricao, {outras} "
        "FROM eventos e WHERE e.id = ?", (row["id"],)).fetchone())
    ev["lotes"] = [dict(r) for r in con.execute(
        "SELECT nome, preco, taxa, gratis, esgotado FROM lotes "
        "WHERE evento_id = ? ORDER BY ordem", (row["id"],))]
    con.close()
    return ev


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
