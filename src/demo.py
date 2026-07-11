"""PoC ponta a ponta: raspa as fontes -> grava na base -> consulta em linguagem natural.

Fontes: Sympla, Ingresse e Shotgun, unificadas no mesmo schema.
Escopo do PoC: festas/baladas em Brasília.

Uso:
    python src/demo.py                 # raspa as 3 fontes e roda consultas de exemplo
    python src/demo.py --sem-shotgun   # pula o Shotgun (lento, usa navegador)
    python src/demo.py --so-consultar  # pula a raspagem, so consulta o que ja tem
"""

import sys
from datetime import datetime, timezone

import consulta
import store
from scrapers import sympla, ingresse, shotgun


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
    total = con.execute("SELECT COUNT(*) AS n FROM eventos").fetchone()["n"]
    porfonte = {r["fonte"]: r["n"] for r in con.execute(
        "SELECT fonte, COUNT(*) AS n FROM eventos GROUP BY fonte")}
    print(f"\n{total_novos} eventos gravados/atualizados. "
          f"Base tem {total} eventos. Por fonte: {porfonte}\n")
    con.close()


def consultar(termo, inicio=None, fim=None, cidade=None, limite=10):
    """Simula o que um agente de IA faria: traduz a intencao em filtros.

    Delega para a camada canonica (consulta.buscar_eventos), que normaliza as
    datas de formatos mistos antes de comparar e ja esconde ruido/duplicatas.
    """
    return consulta.buscar_eventos(texto=termo, cidade=cidade,
                                   data_inicio=inicio, data_fim=fim,
                                   limite=limite)


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
