"""Teste executável da fronteira cru → tratado: é o `cru` que produz a prata.

Este arquivo mudou de natureza na fatia 7 (spec 20260728_arquitetura-medalhao).
Antes ele testava que o upsert da coleta gravava o payload na Bronze de
brinde — ou seja, testava a violação de camada do NI-55. Agora ele testa o
contrário: **nada além do `cru` entra em `tratado.eventos`**, e o teste de
FRONTEIRA no fim (§10) apaga a prata inteira e confere que o tratamento a
reproduz.

Cobre também: append-only (versão nova só quando o payload muda, `visto_em`
avançando mesmo quando não muda), a guarda de era do §6.3, os lotes de
ingresso, o NI-18 (cortesia não mascara preço) e a guarda de nome do NI-17.

Usa o banco descartável eventos_teste no Neon (não toca a base de produção —
ver tests/base_teste.py).

Uso: python tests/test_bronze.py
"""

import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from base import conexao, texto
from coleta import gravar
from coleta import ingresse as ingresse_coleta  # noqa: E402
from coleta import sympla as sympla_coleta  # noqa: E402
from coleta import zig as zig_coleta  # noqa: E402
from pipeline import atualizar  # noqa: E402
from tratamento import comum
from servico import consulta  # noqa: E402

import base_teste  # noqa: E402

# Redireciona a base para o banco descartável antes de qualquer conectar().
base_teste.preparar()

TS = "2026-07-10T00:00:00+00:00"


def sympla(id_, **kw):
    """Payload de catálogo do Sympla com o mínimo que a normalização exige."""
    p = {"id": int(id_) if id_.isdigit() else id_,
         "name": f"Evento sympla:{id_}",
         "start_date": "2026-07-11T22:00:00+00:00", "end_date": None,
         "url": f"https://x/sympla:{id_}", "location": {"city": "Brasília",
                                                        "state": "DF"}}
    p.update(kw)
    return p


def shotgun(slug, **kw):
    p = {"name": f"Evento shotgun:{slug}",
         "startDate": "2026-07-11T22:00:00+00:00",
         "url": f"https://x/shotgun:{slug}", "location": {}}
    p.update(kw)
    return p


def gravar_catalogo(con, fonte, id_nativo, payload, ts=TS, **extras):
    return gravar.gravar(con, fonte, id_nativo, "catalogo", payload, ts,
                         **extras)


def raw_linhas(con, evento_id):
    """Estado CORRENTE do evento no cru (view _atual, uma linha por origem).

    A tabela por baixo é append-only: guarda todas as versões. Quem quer o
    histórico consulta `cru.<fonte>`; quem quer o estado consulta `_atual`.
    """
    fonte, _, id_nativo = evento_id.partition(":")
    return con.execute(
        f"SELECT origem, payload, raspado_em, visto_em FROM cru.{fonte}_atual "
        "WHERE id_nativo = %s ORDER BY origem", (id_nativo,)).fetchall()


def versoes(con, fonte, id_nativo, origem):
    """Quantas versões o append-only guardou para uma chave."""
    return con.execute(
        f"SELECT count(*) AS n FROM cru.{fonte} "
        "WHERE id_nativo = %s AND origem = %s",
        (id_nativo, origem)).fetchone()["n"]


def impressao(con):
    """Impressão digital do conteúdo de `tratado` que o tratamento produz.

    Só as colunas que saem do cru: `sumido`, `ruido` e `dedupe_*` são de outras
    camadas e não entram na comparação do teste de fronteira.
    """
    cols = ",".join(comum.COLS_EVENTO)
    ev = con.execute(f"SELECT {cols} FROM tratado.eventos ORDER BY id").fetchall()
    lt = con.execute("SELECT evento_id, ordem, nome, preco, taxa, gratis, "
                     "esgotado FROM tratado.lotes "
                     "ORDER BY evento_id, ordem").fetchall()
    bruto = json.dumps([[dict(r) for r in ev], [dict(r) for r in lt]],
                       sort_keys=True, default=str)
    return hashlib.md5(bruto.encode()).hexdigest(), len(ev), len(lt)


def main():
    con = conexao.conectar()

    # --- o evento nasce do cru, e só dele ---
    payload = sympla("1", name="Festa",
                     location={"neighborhood": "Asa Norte ", "city": "Brasília"},
                     **{"descrição com separador unicode": "a b"})
    gravar_catalogo(con, "sympla", "1", payload)
    linhas = raw_linhas(con, "sympla:1")
    assert len(linhas) == 1 and linhas[0]["origem"] == "catalogo"
    assert json.loads(linhas[0]["payload"]) == payload, "payload não round-tripa"
    comum.aplicar(con)
    ev = dict(con.execute("SELECT nome, url, bairro, raspado_em FROM "
                          "tratado.eventos WHERE id = 'sympla:1'").fetchone())
    assert ev["nome"] == "Festa" and ev["url"] == "https://x/sympla:1", ev
    assert ev["bairro"] == "Asa Norte", ev  # com trim
    assert ev["raspado_em"] == TS, "raspado_em tem que vir do cru, não de now()"
    print("cru→prata: o evento inteiro (nome, url, bairro, raspado_em) sai do "
          "payload guardado — ok")

    # --- APPEND-ONLY: payload novo acrescenta versão; igual NÃO acrescenta ---
    # Cada rodada tem seu raspado_em (é componente da PK): duas rodadas com o
    # mesmo conteúdo não podem gerar duas versões, e é isso que o hash resolve.
    assert versoes(con, "sympla", "1", "catalogo") == 1
    p2 = sympla("1", name="Festa")
    gravar_catalogo(con, "sympla", "1", p2, ts="2026-07-11T00:00:00+00:00")
    assert versoes(con, "sympla", "1", "catalogo") == 2, "payload novo não virou versão"
    linhas = raw_linhas(con, "sympla:1")
    assert len(linhas) == 1 and json.loads(linhas[0]["payload"]) == p2, \
        "a view _atual tem que devolver só a versão mais recente"
    # o MESMO payload numa rodada nova NÃO gera versão — e nem se as chaves
    # vierem em outra ordem, porque o hash é da forma canônica (sort_keys)
    gravar_catalogo(con, "sympla", "1", dict(reversed(list(p2.items()))),
                    ts="2026-07-12T00:00:00+00:00")
    assert versoes(con, "sympla", "1", "catalogo") == 2, \
        "payload igual (ou só reordenado) não pode gerar versão nova"
    # ...mas o AVISTAMENTO conta: sem isto, `sumido` marcaria como "saiu do
    # catálogo" todo evento que simplesmente não mudou desde a rodada passada.
    assert raw_linhas(con, "sympla:1")[0]["visto_em"] == \
        "2026-07-12T00:00:00+00:00", "visto_em não avançou com o payload igual"
    # e o histórico responde por data, que é o que o append-only compra
    antigo = con.execute(
        "SELECT payload FROM cru.sympla WHERE id_nativo = '1' "
        "AND origem = 'catalogo' ORDER BY raspado_em LIMIT 1").fetchone()
    assert json.loads(antigo["payload"]) == payload, \
        "a versão original tem que continuar consultável"
    print("cru: append-only — payload novo vira versão, igual não (mas avança "
          "visto_em); _atual devolve a última e o histórico continua lá — ok")

    # --- payload de detalhe convive com o de catálogo (PK composta) ---
    gravar.gravar(con, "sympla", "1", "detalhe",
                  {"name": "Festa", "detail": "<p>oi</p>"},
                  "2026-07-10T01:00:00+00:00")
    origens = [r["origem"] for r in raw_linhas(con, "sympla:1")]
    assert origens == ["catalogo", "detalhe"], origens
    comum.aplicar(con)
    assert con.execute("SELECT descricao FROM tratado.eventos WHERE id = "
                       "'sympla:1'").fetchone()["descricao"] == "oi", \
        "a descrição tem que sair do payload de detalhe, sem rede"
    print("cru: catálogo e detalhe coexistem; a descrição deriva do detalhe — ok")

    # --- GUARDA DO §6.3: payload que não é deste evento não vira evento ---
    # É o caso da era de API antiga: o parser novo acha campos homônimos por
    # coincidência e degradaria em silêncio. Errar para o lado de NÃO gravar.
    gravar_catalogo(con, "sympla", "999", sympla("111"))       # id não bate
    gravar_catalogo(con, "sympla", "998", sympla("998", url=None))  # sem url
    contagem = comum.aplicar(con)
    reprovados = {r["evento_id"] for r in contagem["rejeitados"]}
    assert reprovados == {"sympla:999", "sympla:998"}, contagem["rejeitados"]
    assert con.execute("SELECT count(*) AS n FROM tratado.eventos WHERE id IN "
                       "('sympla:999', 'sympla:998')").fetchone()["n"] == 0
    print("guarda §6.3: payload de outro id / sem url é reprovado e reportado, "
          "não vira evento — ok")

    # --- derivação a seco: bairro vem do bruto do Sympla, com trim ---
    gravar_catalogo(con, "sympla", "3",
                    sympla("3", location={"neighborhood": "Ceilândia"}))
    gravar_catalogo(con, "sympla", "4", sympla("4", location={}))
    gravar_catalogo(con, "shotgun", "5",
                    shotgun("5", location={"neighborhood": "não é sympla"}),
                    cidade_label="Brasília", estado_label="DF")
    contagem = comum.aplicar(con)
    bairros = {r["id"]: r["bairro"]
               for r in con.execute("SELECT id, bairro FROM tratado.eventos")}
    assert bairros["sympla:3"] == "Ceilândia"
    assert bairros["sympla:4"] is None
    assert bairros["shotgun:5"] is None, "derivação do sympla não vale p/ shotgun"
    assert contagem["bairro"] == 1, contagem
    # sympla:1 tinha 'Asa Norte' no 1º payload, mas o cru atual é o 2º: a
    # derivação segue a versão CORRENTE, não o histórico.
    assert bairros["sympla:1"] is None
    print("prata: derivação preenche bairro só de (sympla, catalogo) — ok")

    # --- idempotência: aplicar 2x = mesmo estado ---
    antes = impressao(con)
    comum.aplicar(con)
    assert impressao(con) == antes, "aplicar() não é idempotente"
    print("prata: reconstrução idempotente — ok")

    # --- reset: bruto que perde o campo derruba a coluna na próxima aplicação ---
    gravar_catalogo(con, "sympla", "3", sympla("3", location={}),
                    ts="2026-07-10T02:00:00+00:00")
    comum.aplicar(con)
    assert con.execute("SELECT bairro FROM tratado.eventos WHERE id = 'sympla:3'"
                       ).fetchone()["bairro"] is None
    print("prata: recalcula do zero (não eterniza valor de payload antigo) — ok")

    # --- Prata: lotes + preço/esgotado/cancelado/popularidade ---
    gravar_catalogo(con, "sympla", "p1",
                    sympla("p1", name="Festa Com Cortesia Esgotada",
                           global_score=777, location={}))
    gravar_catalogo(con, "ingresse", "p4",
                    {"id": "p4", "title": "Passaporte Esgotado",
                     "slug": "ingresse:p4", "place": {},
                     "event_date": "2026-07-11T22:00:00+00:00"})
    gravar_catalogo(con, "shotgun", "p2", shotgun("p2", name="Show Esgotado", **{
        "offers": [{"name": "Pista", "price": "30",
                    "availability": "https://schema.org/SoldOut"}],
        "eventStatus": "https://schema.org/EventScheduled"}),
        cidade_label="Brasília", estado_label="DF")
    gravar_catalogo(con, "shotgun", "p3", shotgun("p3", name="Show Cancelado", **{
        "offers": {"lowPrice": 25, "availability": "https://schema.org/InStock"},
        "eventStatus": "https://schema.org/EventCancelled"}),
        cidade_label="Brasília", estado_label="DF")
    ts = "2026-07-10T03:00:00+00:00"
    gravar.gravar(con, "sympla", "p1", "detalhe",
                  {"name": "Festa Com Cortesia Esgotada", "cancelled": False}, ts)
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
    longa = ("Aniversário de 13 anos da HOUSE CLUB, line-up completo de DJs a "
             "noite toda. " + "Detalhes. " * 50)
    gravar_catalogo(con, "sympla", "hc", sympla("hc", name="HOUSE CLUB 13 ANOS"))
    gravar_catalogo(con, "sympla", "sc", sympla("sc", name="Evento Só Cortesia"))
    gravar.gravar(con, "sympla", "hc", "detalhe",
                  {"name": "HOUSE CLUB 13 ANOS", "detail": longa}, ts)
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
    print("NI-18: cortesia não mascara preço pago; só-cortesia = grátis — ok")

    # --- TESTE DE FRONTEIRA (spec §10): a prata é descartável de verdade ---
    # Apaga `tratado` inteira e confere que o tratamento a reproduz byte a byte
    # a partir do cru. É o teste que o NI-55 não passava: até a fatia 7 não
    # existia uma linha de código que lesse o bruto e produzisse o evento.
    esperado = impressao(con)
    con.execute("DELETE FROM tratado.lotes")
    con.execute("DELETE FROM tratado.eventos WHERE fonte <> 'instagram'")
    assert con.execute("SELECT count(*) AS n FROM tratado.eventos"
                       ).fetchone()["n"] == 0
    comum.aplicar(con)
    obtido = impressao(con)
    assert obtido == esperado, f"a prata não se reconstrói: {obtido} != {esperado}"
    print(f"FRONTEIRA: prata apagada e reconstruída do cru — {esperado[1]} "
          f"eventos e {esperado[2]} lotes idênticos — ok")

    con.commit()

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

    # --- NI-17: guarda de nome (usada na coleta E na leitura do payload) ---
    assert texto.mesmo_nome(
        "The Beatles Abbey Road - Ultimate Tribute",
        "Polvo Na Cozinha - Manu Zappa") is False
    assert texto.mesmo_nome(
        "Evento Totalmente Grátis Está Esgotado",
        "Sempre Foi Baile @Ephigenia") is False  # troca real em URL comum
    assert texto.mesmo_nome("Arraiá do Brabo", "ARRAIÁ  DO BRABO") is True
    assert texto.mesmo_nome("DOMINGÃO | PARTE 2", "DOMINGÃO") is True
    assert texto.mesmo_nome("Festa", None) is False

    # A guarda roda na COLETA, antes de o payload entrar no cru — e SÓ lá, de
    # propósito. Repeti-la na leitura foi testado contra a base de produção em
    # 2026-07-28 e reprovado: o catálogo se move (produtor renomeia evento), e
    # a guarda passaria a descartar descrição boa de evento com o id certo.
    # Ver o comentário do CONFERIR em src/tratamento/sympla.py.
    gravar_catalogo(con, "sympla", "77",
                    sympla("77", name="Festa Legítima",
                           url="https://www.sympla.com.br/evento/festa/77"))
    sympla_coleta.raspar_descricao = lambda id_url: {
        "nome": "Polvo Na Cozinha",  # o BFF devolveu OUTRO evento (NI-17)
        "payload": {"name": "Polvo Na Cozinha", "detail": "descrição alheia"}}
    # as outras fontes da fila não podem sair para a rede dentro de um teste
    def _sem_rede(_):
        raise RuntimeError("o teste não fala com a rede")
    ingresse_coleta.raspar_descricao = _sem_rede
    zig_coleta.raspar_descricao = _sem_rede
    erros = []
    r = atualizar._descrever(con, erros, pausa=0)
    assert r["trocados"] == 1 and r["buscadas"] == 0, r
    meu = [e for e in erros if e["evento_id"] == "sympla:77"]
    assert len(meu) == 1 and "NI-17" in meu[0]["erro"], erros
    assert not [x for x in raw_linhas(con, "sympla:77")
                if x["origem"] == "detalhe"], \
        "payload com nome divergente não pode nem entrar no cru"
    comum.aplicar(con)
    assert con.execute("SELECT descricao FROM tratado.eventos WHERE id = "
                       "'sympla:77'").fetchone()["descricao"] is None
    print("NI-17: nome divergente barrado na COLETA (não chega ao cru) — ok")

    con.commit()
    con.close()
    print("\nOK — a prata se reconstrói do cru e as guardas se comportam como "
          "a spec pede.")


if __name__ == "__main__":
    main()
