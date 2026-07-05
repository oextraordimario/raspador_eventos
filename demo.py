"""PoC ponta a ponta: raspa as fontes -> grava SQLite -> consulta em linguagem natural.

Fontes: Sympla, Ingresse e Shotgun, unificadas no mesmo schema.
Escopo do PoC: festas/baladas em Brasília.

Uso:
    python demo.py                 # raspa as 3 fontes e roda consultas de exemplo
    python demo.py --sem-shotgun   # pula o Shotgun (lento, usa navegador)
    python demo.py --so-consultar  # pula a raspagem, so consulta o que ja tem
"""

import sys
from datetime import datetime, timezone

import store
import sympla
import ingresse
import shotgun


def coletar(incluir_shotgun=True):
    con = store.conectar()
    total_novos = 0

    print("[Sympla] festas/baladas de Brasília...")
    total_novos += store.upsert_eventos(con, sympla.raspar(
        city="brasilia", state="DF", location="Brasília", max_paginas=8))

    print("[Ingresse] eventos de Brasília...")
    total_novos += store.upsert_eventos(con, ingresse.raspar())

    if incluir_shotgun:
        print("[Shotgun] eventos de Brasília (via navegador)...")
        total_novos += store.upsert_eventos(con, shotgun.raspar(
            city_slug="brasilia"))

    store.reconstruir_fts(con)
    total = con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
    porfonte = dict(con.execute(
        "SELECT fonte, COUNT(*) FROM eventos GROUP BY fonte").fetchall())
    print(f"\n{total_novos} eventos gravados/atualizados. "
          f"Base tem {total} eventos. Por fonte: {porfonte}\n")
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
        print(f"  • {quando} | [{r['fonte']}] {r['nome'][:55]}")
        print(f"      {r['local_nome'] or '?'} — {r['cidade'] or '?'} | {r['url']}")


if __name__ == "__main__":
    if "--so-consultar" not in sys.argv:
        coletar(incluir_shotgun="--sem-shotgun" not in sys.argv)

    agora = datetime.now(timezone.utc).isoformat()

    # Caso de uso 1: "quais festas de pagode vão ter?"
    _mostrar('"pagode" em Brasília (futuros)',
             consultar("pagode", inicio=agora, cidade="Brasília"))

    # Caso de uso 2: baladas/festas em geral
    _mostrar('"balada OR festa OR club" em Brasília (futuros)',
             consultar("balada OR festa OR club OR party", inicio=agora,
                       cidade="Brasília"))

    # Caso de uso 3: tudo que tem, ordenado por data (as próximas festas)
    _mostrar("Próximas festas/baladas em Brasília",
             consultar(None, inicio=agora, cidade="Brasília"))
