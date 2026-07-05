"""Camada de consulta da base unificada de eventos.

Contrato pensado para virar uma tool MCP: uma unica funcao parametrizada,
todos os argumentos opcionais, retorno em lista de dicts (JSON-serializavel).

Pegadinha tratada aqui: as fontes gravam datas ISO em formatos diferentes
(Sympla/Ingresse usam "+00:00", Shotgun usa ".000Z"). A comparacao lexical
de strings falha entre esses formatos -- por exemplo, um evento Shotgun no
mesmo instante que um limite superior "+00:00" seria excluido por engano.
Por isso normalizamos toda data para um instante canonico antes de comparar.
"""

from datetime import datetime, timezone

import store

# Campos uteis expostos ao agente (subconjunto enxuto da tabela).
CAMPOS = ["nome", "fonte", "start_date", "end_date", "cidade", "estado",
          "local_nome", "endereco", "categoria", "organizador", "url", "imagem"]


def _norm_ts(iso):
    """Normaliza uma data ISO (qualquer formato das fontes) para um texto
    comparavel/ordenavel de forma consistente. Retorna None se nao parsear."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    # Sem timezone: assume UTC. Com timezone: converte para UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def buscar_eventos(texto=None, cidade=None, data_inicio=None, data_fim=None,
                   limite=20):
    """Busca eventos na base unificada.

    Args:
        texto: busca textual (FTS) sobre nome/categoria. Aceita a sintaxe do
            FTS5 (ex.: "funk OR techno"). Omitido = sem filtro de texto.
        cidade: filtro exato por cidade.
        data_inicio: limite inferior (ISO) sobre start_date, inclusivo.
        data_fim: limite superior (ISO) sobre start_date, inclusivo.
        limite: numero maximo de resultados (ordenados por start_date).

    Returns:
        Lista de dicts (nunca sqlite3.Row), ordenada por start_date.
    """
    con = store.conectar()
    # Funcao SQL para comparar datas normalizadas (contorna os formatos mistos).
    con.create_function("norm_ts", 1, _norm_ts, deterministic=True)

    where, params = [], []
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

    sql = f"SELECT {', '.join(CAMPOS)} FROM eventos e"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY norm_ts(e.start_date) LIMIT ?"
    params.append(limite)

    rows = con.execute(sql, params).fetchall()
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
                if _norm_ts(e["start_date"]) and _norm_ts(e["start_date"]) < agora]
    print(f"    fontes presentes: {fontes} | eventos passados que vazaram: {len(passados)}")

    # 3) um genero (funk OR techno).
    _mostrar('"funk OR techno" (futuros)',
             buscar_eventos(texto="funk OR techno", cidade="Brasília",
                            data_inicio=agora))

    # 4) caso que deve retornar vazio.
    _mostrar("Texto sem correspondencia (deve vir vazio)",
             buscar_eventos(texto="xyzzyabracadabra123"))
