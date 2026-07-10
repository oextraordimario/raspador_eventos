"""Teste executável das camadas Bronze (eventos_raw + derivação a seco) e
Prata (preço/esgotado/cancelado/popularidade + efeito na consulta), mais a
guarda de nome do NI-17. Usa uma base SQLite descartável (não toca
data/eventos.db). Specs: docs/specs/20260710_camada-bronze e
20260710_camada-prata.

Uso: python tests/test_bronze.py
"""

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import store  # noqa: E402
import derivar  # noqa: E402
import consulta  # noqa: E402

# Redireciona a base para um arquivo descartável antes de qualquer conectar().
store.DB_PATH = Path(tempfile.mkdtemp()) / "eventos_teste.db"


def evento(id_, **kw):
    fonte = id_.split(":")[0]
    e = {
        "id": id_, "fonte": fonte, "id_nativo": id_.split(":")[1],
        "nome": f"Evento {id_}", "start_date": "2026-07-11T22:00:00+00:00",
        "end_date": None, "cidade": "Brasília", "estado": "DF",
        "local_nome": None, "endereco": None, "lat": None, "lon": None,
        "categoria": None, "organizador": None, "url": f"https://x/{id_}",
        "imagem": None, "raspado_em": "2026-07-10T00:00:00+00:00",
    }
    e.update(kw)
    return e


def raw_linhas(con, evento_id):
    return con.execute(
        "SELECT origem, payload, raspado_em FROM eventos_raw "
        "WHERE evento_id = ? ORDER BY origem", (evento_id,)).fetchall()


def main():
    con = store.conectar()

    # --- upsert com _raw grava a Bronze; sem _raw segue funcionando ---
    payload = {"id": 1, "name": "Festa", "location": {"neighborhood": "Asa Norte "},
               "descrição com separador unicode": "a b"}
    store.upsert_eventos(con, [
        evento("sympla:1", nome="Festa", _raw=payload),
        evento("sympla:2", nome="Sem raw"),
    ])
    linhas = raw_linhas(con, "sympla:1")
    assert len(linhas) == 1 and linhas[0]["origem"] == "catalogo"
    assert json.loads(linhas[0]["payload"]) == payload, "payload não round-tripa"
    assert raw_linhas(con, "sympla:2") == []
    cols = {r[1] for r in con.execute("PRAGMA table_info(eventos)")}
    assert "_raw" not in cols, "_raw vazou como coluna de eventos"
    print("bronze: upsert grava eventos_raw, payload round-tripa, _raw não vaza — ok")

    # --- upsert repetido não duplica; último payload vence ---
    store.upsert_eventos(con, [evento("sympla:1", nome="Festa",
                                      _raw={"id": 1, "v": 2})])
    linhas = raw_linhas(con, "sympla:1")
    assert len(linhas) == 1 and json.loads(linhas[0]["payload"]) == {"id": 1, "v": 2}
    print("bronze: upsert repetido não duplica, último payload vence — ok")

    # --- payload de detalhe convive com o de catálogo (PK composta) ---
    store.gravar_raw(con, "sympla:1", "detalhe", {"detail": "<p>oi</p>"},
                     "2026-07-10T01:00:00+00:00")
    origens = [r["origem"] for r in raw_linhas(con, "sympla:1")]
    assert origens == ["catalogo", "detalhe"], origens
    print("bronze: catálogo e detalhe coexistem por evento — ok")

    # --- derivação a seco: bairro vem do bruto do Sympla, com trim ---
    store.upsert_eventos(con, [
        evento("sympla:3", _raw={"location": {"neighborhood": "Ceilândia"}}),
        evento("sympla:4", _raw={"location": {}}),           # sem bairro
        evento("shotgun:5", _raw={"location": {"neighborhood": "não é sympla"}}),
    ])
    contagem = derivar.aplicar(con)
    bairros = dict(con.execute("SELECT id, bairro FROM eventos"))
    assert bairros["sympla:3"] == "Ceilândia"
    assert bairros["sympla:4"] is None
    assert bairros["sympla:2"] is None, "evento sem raw não deriva"
    assert bairros["shotgun:5"] is None, "derivação do sympla não vale p/ shotgun"
    assert contagem["bairro"] == 1, contagem
    # sympla:1 tinha 'Asa Norte' no 1º payload, mas o raw foi substituído por
    # {"id":1,"v":2}: a derivação segue o ÚLTIMO payload, não o histórico.
    assert bairros["sympla:1"] is None
    print("bronze: derivação preenche bairro só de (sympla, catalogo) — ok")

    # --- idempotência: aplicar 2x = mesmo estado ---
    antes = sorted(bairros.items())
    derivar.aplicar(con)
    depois = sorted(tuple(r) for r in con.execute("SELECT id, bairro FROM eventos"))
    assert depois == antes
    print("bronze: derivação idempotente — ok")

    # --- reset: bruto que perde o campo derruba a coluna na próxima aplicação ---
    store.gravar_raw(con, "sympla:3", "catalogo", {"location": {}},
                     "2026-07-10T02:00:00+00:00")
    derivar.aplicar(con)
    assert con.execute("SELECT bairro FROM eventos WHERE id = 'sympla:3'"
                       ).fetchone()[0] is None
    print("bronze: recalcula do zero (não eterniza valor de payload antigo) — ok")

    # --- Prata: derivações de preço/esgotado/cancelado/popularidade ---
    store.upsert_eventos(con, [
        evento("sympla:p1", nome="Festa Com Lote Grátis",
               _raw={"global_score": 777, "location": {}}),
        evento("ingresse:p4", nome="Passaporte Esgotado"),
        evento("shotgun:p2", nome="Show Esgotado", _raw={
            "offers": [{"price": "30", "availability": "https://schema.org/SoldOut"}],
            "eventStatus": "https://schema.org/EventScheduled"}),
        evento("shotgun:p3", nome="Show Cancelado", _raw={
            "offers": {"lowPrice": 25, "availability": "https://schema.org/InStock"},
            "eventStatus": "https://schema.org/EventCancelled"}),
    ])
    ts = "2026-07-10T03:00:00+00:00"
    store.gravar_raw(con, "sympla:p1", "detalhe", {"cancelled": False}, ts)
    store.gravar_raw(con, "sympla:p1", "tickets", {"tickets": [
        {"show": True, "isFree": False, "currentAvailableQty": 5,
         "salePriceWithDiscountMonetary": {"decimal": 44.0}},
        {"show": True, "isFree": True, "currentAvailableQty": 0},
    ]}, ts)
    store.gravar_raw(con, "ingresse:p4", "tickets", {"detail": {"responseData": [
        {"type": [{"price": 400, "status": "finished"},
                  {"price": 200, "status": "finished"},
                  {"price": 1, "status": "available", "hidden": True}]},
    ]}}, ts)
    derivar.aplicar(con)

    def prata(ev_id):
        return dict(con.execute(
            "SELECT preco_min, esgotado, cancelado, popularidade "
            "FROM eventos WHERE id = ?", (ev_id,)).fetchone())

    assert prata("sympla:p1") == {"preco_min": 0.0, "esgotado": 0,
                                  "cancelado": 0, "popularidade": 777}, \
        prata("sympla:p1")  # lote grátis → preço 0; havia vaga → não esgotado
    assert prata("ingresse:p4") == {"preco_min": 200.0, "esgotado": 1,
                                    "cancelado": None, "popularidade": None}, \
        prata("ingresse:p4")  # lote oculto não conta; todos finished → esgotado
    assert prata("shotgun:p2") == {"preco_min": 30.0, "esgotado": 1,
                                   "cancelado": 0, "popularidade": None}
    assert prata("shotgun:p3") == {"preco_min": 25.0, "esgotado": 0,
                                   "cancelado": 1, "popularidade": None}
    print("prata: preço/esgotado/cancelado/popularidade derivados dos payloads — ok")

    # --- Prata na consulta: cancelado some por padrão, esgotado aparece ---
    todos = consulta.buscar_eventos(limite=200)
    nomes = [e["nome"] for e in todos]
    assert "Show Cancelado" not in nomes, "cancelado deveria sumir da consulta"
    esg = [e for e in todos if e["nome"] == "Show Esgotado"]
    assert esg and esg[0]["esgotado"] == 1 and esg[0]["preco_min"] == 30.0
    assert "Show Cancelado" in [e["nome"] for e in
                                consulta.buscar_eventos(limite=200,
                                                        incluir_ruido=True)]
    print("prata: consulta esconde cancelado, expõe esgotado/preço — ok")

    # --- NI-17: guarda de nome do _descrever rejeita evento trocado ---
    import atualizar  # noqa: E402  (importa playwright via scrapers; só p/ _mesmo_nome)
    assert atualizar._mesmo_nome(
        "The Beatles Abbey Road - Ultimate Tribute",
        "Polvo Na Cozinha - Manu Zappa") is False
    assert atualizar._mesmo_nome(
        "Evento Totalmente Grátis Está Esgotado",
        "Sempre Foi Baile @Ephigenia") is False  # troca real em URL comum
    assert atualizar._mesmo_nome("Arraiá do Brabo", "ARRAIÁ  DO BRABO") is True
    assert atualizar._mesmo_nome("DOMINGÃO | PARTE 2", "DOMINGÃO") is True
    assert atualizar._mesmo_nome("Festa", None) is False
    print("NI-17: nome divergente rejeitado, prefixo/caixa/espaço aceitos — ok")

    con.close()
    print("\nOK — camada Bronze e guarda do NI-17 se comportam como a spec pede.")


if __name__ == "__main__":
    main()
