"""Teste executável das camadas Bronze (eventos_raw + derivação a seco) e
Prata (lotes de ingresso, preço/tem_gratis/esgotado/cancelado/popularidade e
detalhar_evento), mais a guarda de nome do NI-17. Usa o banco descartável
eventos_teste no Neon (não toca a base de produção — ver tests/base_teste.py).
Specs: docs/specs/20260710_camada-bronze, 20260710_camada-prata e
20260710_lotes-ingressos.

Uso: python tests/test_bronze.py
"""

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from base import conexao
from coleta import gravar
from tratamento import comum
from servico import consulta  # noqa: E402

import base_teste  # noqa: E402

# Redireciona a base para o banco descartável antes de qualquer conectar().
base_teste.preparar()


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
    """Estado CORRENTE do evento no cru (view _atual, uma linha por origem).

    A tabela por baixo é append-only: guarda todas as versões. Quem quer o
    histórico consulta `cru.<fonte>`; quem quer o estado consulta `_atual`.
    """
    fonte, _, id_nativo = evento_id.partition(":")
    return con.execute(
        f"SELECT origem, payload, raspado_em FROM cru.{fonte}_atual "
        "WHERE id_nativo = %s ORDER BY origem", (id_nativo,)).fetchall()


def versoes(con, fonte, id_nativo, origem):
    """Quantas versões o append-only guardou para uma chave."""
    return con.execute(
        f"SELECT count(*) AS n FROM cru.{fonte} "
        "WHERE id_nativo = %s AND origem = %s",
        (id_nativo, origem)).fetchone()["n"]


def main():
    con = conexao.conectar()

    # --- upsert com _raw grava a Bronze; sem _raw segue funcionando ---
    payload = {"id": 1, "name": "Festa", "location": {"neighborhood": "Asa Norte "},
               "descrição com separador unicode": "a b"}
    comum.upsert_eventos(con, [
        evento("sympla:1", nome="Festa", _raw=payload),
        evento("sympla:2", nome="Sem raw"),
    ])
    linhas = raw_linhas(con, "sympla:1")
    assert len(linhas) == 1 and linhas[0]["origem"] == "catalogo"
    assert json.loads(linhas[0]["payload"]) == payload, "payload não round-tripa"
    assert raw_linhas(con, "sympla:2") == []
    cols = {r["column_name"] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'tratado' AND table_name = 'eventos'")}
    assert "_raw" not in cols, "_raw vazou como coluna de eventos"
    print("bronze: upsert grava eventos_raw, payload round-tripa, _raw não vaza — ok")

    # --- APPEND-ONLY: payload novo acrescenta versão; igual NÃO acrescenta ---
    # Cada rodada tem seu raspado_em (é componente da PK): duas rodadas com o
    # mesmo conteúdo não podem gerar duas versões, e é isso que o hash resolve.
    assert versoes(con, "sympla", "1", "catalogo") == 1
    comum.upsert_eventos(con, [evento("sympla:1", nome="Festa",
                                      raspado_em="2026-07-11T00:00:00+00:00",
                                      _raw={"id": 1, "v": 2})])
    assert versoes(con, "sympla", "1", "catalogo") == 2, "payload novo não virou versão"
    linhas = raw_linhas(con, "sympla:1")
    assert len(linhas) == 1 and json.loads(linhas[0]["payload"]) == {"id": 1, "v": 2}, \
        "a view _atual tem que devolver só a versão mais recente"
    # o MESMO payload numa rodada nova NÃO gera versão — e nem se as chaves
    # vierem em outra ordem, porque o hash é da forma canônica (sort_keys)
    comum.upsert_eventos(con, [evento("sympla:1", nome="Festa",
                                      raspado_em="2026-07-12T00:00:00+00:00",
                                      _raw={"v": 2, "id": 1})])
    assert versoes(con, "sympla", "1", "catalogo") == 2, \
        "payload igual (ou só reordenado) não pode gerar versão nova"
    # e o histórico responde por data, que é o que o append-only compra
    antigo = con.execute(
        "SELECT payload FROM cru.sympla WHERE id_nativo = '1' "
        "AND origem = 'catalogo' ORDER BY raspado_em LIMIT 1").fetchone()
    assert json.loads(antigo["payload"]) == payload, \
        "a versão original tem que continuar consultável"
    print("bronze: append-only — payload novo vira versão, igual não; _atual "
          "devolve a última e o histórico continua lá — ok")

    # --- payload de detalhe convive com o de catálogo (PK composta) ---
    gravar.gravar(con, "sympla", "1", "detalhe", {"detail": "<p>oi</p>"},
                     "2026-07-10T01:00:00+00:00")
    origens = [r["origem"] for r in raw_linhas(con, "sympla:1")]
    assert origens == ["catalogo", "detalhe"], origens
    print("bronze: catálogo e detalhe coexistem por evento — ok")

    # --- derivação a seco: bairro vem do bruto do Sympla, com trim ---
    comum.upsert_eventos(con, [
        evento("sympla:3", _raw={"location": {"neighborhood": "Ceilândia"}}),
        evento("sympla:4", _raw={"location": {}}),           # sem bairro
        evento("shotgun:5", _raw={"location": {"neighborhood": "não é sympla"}}),
    ])
    contagem = comum.aplicar(con)
    bairros = {r["id"]: r["bairro"]
               for r in con.execute("SELECT id, bairro FROM tratado.eventos")}
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
    comum.aplicar(con)
    depois = sorted((r["id"], r["bairro"])
                    for r in con.execute("SELECT id, bairro FROM tratado.eventos"))
    assert depois == antes
    print("bronze: derivação idempotente — ok")

    # --- reset: bruto que perde o campo derruba a coluna na próxima aplicação ---
    gravar.gravar(con, "sympla", "3", "catalogo", {"location": {}},
                     "2026-07-10T02:00:00+00:00")
    comum.aplicar(con)
    assert con.execute("SELECT bairro FROM tratado.eventos WHERE id = 'sympla:3'"
                       ).fetchone()["bairro"] is None
    print("bronze: recalcula do zero (não eterniza valor de payload antigo) — ok")

    # --- Prata: lotes + preço/esgotado/cancelado/popularidade ---
    comum.upsert_eventos(con, [
        evento("sympla:p1", nome="Festa Com Cortesia Esgotada",
               _raw={"global_score": 777, "location": {}}),
        evento("ingresse:p4", nome="Passaporte Esgotado"),
        evento("shotgun:p2", nome="Show Esgotado", _raw={
            "offers": [{"name": "Pista", "price": "30",
                        "availability": "https://schema.org/SoldOut"}],
            "eventStatus": "https://schema.org/EventScheduled"}),
        evento("shotgun:p3", nome="Show Cancelado", _raw={
            "offers": {"lowPrice": 25, "availability": "https://schema.org/InStock"},
            "eventStatus": "https://schema.org/EventCancelled"}),
    ])
    ts = "2026-07-10T03:00:00+00:00"
    gravar.gravar(con, "sympla", "p1", "detalhe", {"cancelled": False}, ts)
    gravar.gravar(con, "sympla", "p1", "tickets", {"tickets": [
        {"show": True, "isFree": False, "currentAvailableQty": 5,
         "salePriceWithDiscountMonetary": {"decimal": 44.0}},
        {"show": True, "isFree": True, "currentAvailableQty": 0},
    ]}, ts)
    gravar.gravar(con, "ingresse", "p4", "tickets", {"detail": {"responseData": [
        {"name": "Passaporte PISTA",
         "type": [{"name": "Inteira", "price": 400, "tax": 40, "status": "finished"},
                  {"name": "Meia", "price": 200, "tax": 20, "status": "finished"},
                  {"price": 1, "status": "available", "hidden": True}]},
    ]}}, ts)
    comum.aplicar(con)

    def prata(ev_id):
        return dict(con.execute(
            "SELECT preco_min, tem_gratis, esgotado, cancelado, popularidade "
            "FROM tratado.eventos WHERE id = %s", (ev_id,)).fetchone())

    # preco_min = menor lote PAGO; cortesia esgotada NÃO liga tem_gratis
    assert prata("sympla:p1") == {"preco_min": 44.0, "tem_gratis": 0,
                                  "esgotado": 0, "cancelado": 0,
                                  "popularidade": 777}, prata("sympla:p1")
    # lote oculto não conta; todos finished → esgotado; preco = price + tax
    assert prata("ingresse:p4") == {"preco_min": 220.0, "tem_gratis": 0,
                                    "esgotado": 1, "cancelado": None,
                                    "popularidade": None}, prata("ingresse:p4")
    assert prata("shotgun:p2") == {"preco_min": 30.0, "tem_gratis": 0,
                                   "esgotado": 1, "cancelado": 0,
                                   "popularidade": None}
    assert prata("shotgun:p3") == {"preco_min": 25.0, "tem_gratis": 0,
                                   "esgotado": 0, "cancelado": 1,
                                   "popularidade": None}
    # nome do lote Ingresse = "setor — lote"
    nomes_lotes = [r["nome"] for r in con.execute(
        "SELECT nome FROM tratado.lotes WHERE evento_id = 'ingresse:p4' ORDER BY ordem")]
    assert nomes_lotes == ["Passaporte PISTA — Inteira", "Passaporte PISTA — Meia"]
    print("prata: preço pago mín./tem_gratis/esgotado/cancelado derivados — ok")

    # --- NI-18: o caso HOUSE CLUB — cortesia não mascara o preço pago ---
    comum.upsert_eventos(con, [
        evento("sympla:hc", nome="HOUSE CLUB 13 ANOS",
               descricao="Aniversário de 13 anos da HOUSE CLUB, line-up "
                         "completo de DJs a noite toda. " + "Detalhes. " * 50),
        evento("sympla:sc", nome="Evento Só Cortesia"),
    ])
    gravar.gravar(con, "sympla", "hc", "tickets", {"tickets": [
        {"show": True, "isFree": True, "currentAvailableQty": 2,
         "name": "CORTESIA FEMININA DA COPA ATÉ 00H"},
        {"show": True, "isFree": False, "currentAvailableQty": 5,
         "name": "HOUSE CLUB MASCULINO 2º LOTE",
         "salePriceWithDiscountMonetary": {"decimal": 49.5},
         "feeMonetary": {"decimal": 4.5}},
        {"show": True, "isFree": False, "currentAvailableQty": 5,
         "name": "HOUSE CLUB FEMININO 2º LOTE",
         "salePriceWithDiscountMonetary": {"decimal": 38.99},
         "feeMonetary": {"decimal": 3.99}},
        {"show": True, "isFree": False, "currentAvailableQty": 5,
         "name": "BISTRÔ ANTECIPADO + 4 ENTRADAS VIP",
         "salePriceWithDiscountMonetary": {"decimal": 418.0},
         "feeMonetary": {"decimal": 38.0}},
    ]}, ts)
    gravar.gravar(con, "sympla", "sc", "tickets", {"tickets": [
        {"show": True, "isFree": True, "currentAvailableQty": 10,
         "name": "Entrada franca"},
    ]}, ts)
    comum.aplicar(con)
    hc = prata("sympla:hc")
    assert hc["preco_min"] == 38.99 and hc["tem_gratis"] == 1 \
        and hc["esgotado"] == 0, hc  # antes da spec: preco_min viria 0.0
    sc = prata("sympla:sc")
    assert sc["preco_min"] is None and sc["tem_gratis"] == 1, \
        sc  # evento grátis: sem lote pago + tem_gratis
    # derivação idempotente também para lotes (DELETE + reinsert)
    n_lotes = con.execute("SELECT COUNT(*) AS n FROM tratado.lotes").fetchone()["n"]
    comum.aplicar(con)
    assert con.execute("SELECT COUNT(*) AS n FROM tratado.lotes").fetchone()["n"] == n_lotes
    print("NI-18: cortesia não mascara preço pago; só-cortesia = grátis — ok")

    # --- detalhar_evento: descrição inteira + lotes na ordem da fonte ---
    det = consulta.detalhar_evento("https://x/sympla:hc")
    assert len(det["descricao"]) > consulta.DESCRICAO_MAX, "descrição veio cortada"
    assert [lt["nome"] for lt in det["lotes"]] == [
        "CORTESIA FEMININA DA COPA ATÉ 00H", "HOUSE CLUB MASCULINO 2º LOTE",
        "HOUSE CLUB FEMININO 2º LOTE", "BISTRÔ ANTECIPADO + 4 ENTRADAS VIP"]
    assert det["lotes"][1] == {"nome": "HOUSE CLUB MASCULINO 2º LOTE",
                               "preco": 49.5, "taxa": 4.5, "gratis": 0,
                               "esgotado": 0}
    assert "erro" in consulta.detalhar_evento("https://x/nao-existe")
    # url de membro não-canônico de dedupe responde pelo canônico
    con.execute("UPDATE tratado.eventos SET dedupe_grupo = 'sympla:hc' "
                "WHERE id IN ('sympla:hc', 'sympla:sc')")
    con.execute("UPDATE tratado.eventos SET dedupe_canonico = 0 WHERE id = 'sympla:sc'")
    con.commit()
    assert consulta.detalhar_evento("https://x/sympla:sc")["nome"] == \
        "HOUSE CLUB 13 ANOS"
    con.execute("UPDATE tratado.eventos SET dedupe_grupo = NULL, dedupe_canonico = 1 "
                "WHERE id IN ('sympla:hc', 'sympla:sc')")
    con.commit()
    print("detalhar_evento: descrição completa, lotes em ordem, erro amigável — ok")

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
    from pipeline import atualizar  # noqa: E402  (só p/ _mesmo_nome)
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
