"""PoC ponta a ponta: raspa Sympla -> grava SQLite -> consulta em linguagem natural.

Uso:
    python demo.py                 # raspa SP e roda consultas de exemplo
    python demo.py --so-consultar  # pula a raspagem, so consulta o que ja tem
"""

import sys
from datetime import datetime, timezone

import store
import sympla


def coletar():
    con = store.conectar()
    print("Raspando eventos de São Paulo no Sympla...")
    eventos = sympla.raspar(city="sao-paulo", state="SP",
                            location="São Paulo", max_paginas=8)
    n = store.upsert_eventos(con, eventos)
    store.reconstruir_fts(con)
    total = con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
    print(f"\n{n} eventos gravados. Base agora tem {total} eventos.\n")
    con.close()


def consultar(termo, inicio=None, fim=None, cidade=None, limite=10):
    """Simula o que um agente de IA faria: traduz a intencao em filtros SQL.

    - termo: busca textual no nome/categoria (FTS)
    - inicio/fim: janela de datas (ISO) -- ex.: um fim de semana
    - cidade: filtro geografico
    """
    con = store.conectar()
    where, params = [], []
    if termo:
        where.append("e.rowid IN (SELECT rowid FROM eventos_fts "
                     "WHERE eventos_fts MATCH ?)")
        params.append(termo)
    if inicio:
        where.append("e.start_date >= ?")
        params.append(inicio)
    if fim:
        where.append("e.start_date <= ?")
        params.append(fim)
    if cidade:
        where.append("e.cidade = ?")
        params.append(cidade)
    sql = "SELECT e.* FROM eventos e"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.start_date LIMIT ?"
    params.append(limite)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return rows


def _mostrar(titulo, rows):
    print(f"\n### {titulo}  ({len(rows)} resultados)")
    if not rows:
        print("  (nenhum)")
        return
    for r in rows:
        quando = (r["start_date"] or "")[:16].replace("T", " ")
        print(f"  • {quando} | {r['nome'][:60]}")
        print(f"      {r['local_nome'] or '?'} — {r['cidade'] or '?'} | {r['url']}")


if __name__ == "__main__":
    if "--so-consultar" not in sys.argv:
        coletar()

    agora = datetime.now(timezone.utc).isoformat()

    # Caso de uso 1: "quais festas de pagode vão ter?"
    _mostrar('"pagode" em São Paulo (futuros)',
             consultar("pagode", inicio=agora, cidade="São Paulo"))

    # Caso de uso 2: shows/música em geral
    _mostrar('"show OR música" em São Paulo (futuros)',
             consultar("show OR musica OR música", inicio=agora,
                       cidade="São Paulo"))
