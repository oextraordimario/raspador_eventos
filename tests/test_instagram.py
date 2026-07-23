"""Teste executável da fonte Instagram (spec 20260723_instagram-como-fonte):
inferência de ano/hora da data do flyer, guarda de derivação (só anúncio com
confiança alta e data futura vira evento), lote sintético do preço do flyer,
exclusão da lógica de sumido, conciliação post ↔ evento de plataforma via
dedupe com aliases de local, e o efeito na consulta. Sem rede pro Monid nem
pro claude -p — o que se testa é a derivação/integração, não os fornecedores
(essas são as camadas 2/3 da validação da spec). Usa o banco descartável
eventos_teste no Neon (ver tests/base_teste.py).

Uso: python tests/test_instagram.py
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import store  # noqa: E402
import derivar  # noqa: E402
import enriquecer  # noqa: E402
import consulta  # noqa: E402
import atualizar  # noqa: E402
from scrapers import instagram  # noqa: E402

import base_teste  # noqa: E402

base_teste.preparar()

# Watchlist de fixture (não usa dados/perfis_instagram.yaml: o teste não pode
# quebrar quando o autor curar a lista real).
WATCHLIST_TESTE = """
- usuario: cultorockbar
  nome: Culto Rock Bar
  tipo: casa
  local_aliases: ["Culto"]
- usuario: produtoraxyz
  nome: Produtora XYZ
  tipo: produtora
"""

AGORA = datetime.now(timezone.utc)
EM_10_DIAS = AGORA + timedelta(days=10)
TAKEN_AT = int(AGORA.timestamp()) - 86400  # post de ontem
DATA_FLYER = f"{EM_10_DIAS.day:02d}/{EM_10_DIAS.month:02d}"


def _post(code, legenda):
    """Payload de post na forma da captura do spike (campos que usamos)."""
    return {"code": code, "taken_at": TAKEN_AT, "media_type": 1,
            "caption": {"text": legenda, "hashtags": [], "mentions": []},
            "image_versions": {"items": [{"url": "https://cdn/expirada.jpg",
                                          "width": 1080}]}}


EXTRACAO_OK = {"e_evento": True, "confianca": "alta", "nome": "Alquimia Dark",
               "data": DATA_FLYER, "hora": "21:00", "preco": 20.0,
               "lineup": ["GABZ", "VELOZZ"], "local": None,
               "observacoes": "entrada 20$ na porta"}


def test_datas():
    # ano inferido: próxima ocorrência a partir da data do post
    jul = int(datetime(2026, 7, 21, tzinfo=timezone.utc).timestamp())
    assert instagram.montar_start_date(
        {"data": "25/07", "hora": "21:00"}, jul) == "2026-07-25T21:00:00-03:00"
    dez = int(datetime(2026, 12, 20, tzinfo=timezone.utc).timestamp())
    assert instagram.montar_start_date(
        {"data": "05/01", "hora": None}, dez) == "2027-01-05T00:00:00-03:00"
    # ano explícito no flyer vence; no passado = retrospectiva, não vira evento
    assert instagram.montar_start_date(
        {"data": "25/07/2027"}, jul) == "2027-07-25T00:00:00-03:00"
    assert instagram.montar_start_date({"data": "25/07/2025"}, jul) is None
    # variações: "25.7", hora "21h", lixo
    assert instagram.montar_start_date(
        {"data": "25.7", "hora": "21h"}, jul) == "2026-07-25T21:00:00-03:00"
    assert instagram.montar_start_date({"data": "31/02"}, jul) is None
    assert instagram.montar_start_date({"data": None}, jul) is None
    assert instagram.montar_start_date({"data": "25/07"}, None) is None
    # data do post é a LOCAL: post das 23h BRT de 21/07 (= 22/07 em UTC)
    # anunciando festa "hoje 21/07" fica em 2026, não rola pro ano seguinte
    tarde = int(datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc).timestamp())
    assert instagram.montar_start_date(
        {"data": "21/07", "hora": "23:30"}, tarde) == "2026-07-21T23:30:00-03:00"
    # data recém-passada sem ano = retrospectiva ("ontem 21/07"), não evento
    # de daqui a ~1 ano (teto INFERENCIA_MAX_DIAS)
    assert instagram.montar_start_date({"data": "20/07"}, tarde) is None
    print("datas: inferência de ano/hora do flyer (fuso local + teto) — ok")


def test_watchlist(tmp):
    perfis = instagram.carregar_watchlist(tmp)
    assert [p["usuario"] for p in perfis] == ["cultorockbar", "produtoraxyz"]
    assert all(p["ativo"] for p in perfis), "default ativo=true"
    aliases = instagram.aliases_local(tmp)
    assert aliases["Culto"] == "Culto Rock Bar"
    assert aliases["Culto Rock Bar"] == "Culto Rock Bar", "canônico mapeia a si"
    assert instagram.carregar_watchlist(tmp + ".nao-existe") == []
    print("watchlist: parse do YAML, defaults e aliases — ok")


def test_derivacao_e_consulta():
    con = store.conectar()
    raspado = AGORA.isoformat()

    # evento de plataforma pro dedupe conciliar: mesmo dia, nome parecido
    # (sim < 0.85 → precisa do local; o alias "Culto" ↔ "Culto Rock Bar" fecha)
    sympla_ev = {
        "id": "sympla:111", "fonte": "sympla", "id_nativo": "111",
        "nome": "Alquimia Dark - Edição Especial",
        "start_date": instagram.montar_start_date(EXTRACAO_OK, TAKEN_AT),
        "end_date": None, "cidade": "Brasília", "estado": "DF",
        "local_nome": "Culto", "endereco": "SCS Q 1", "lat": -15.8, "lon": -47.9,
        "categoria": "musica", "organizador": "Culto",
        "url": "https://sympla.com/alquimia", "imagem": "https://i/x.jpg",
        "raspado_em": raspado, "descricao": "Festa dark", "atracoes": None,
        "preco_min": None,
    }
    store.upsert_eventos(con, [sympla_ev])

    itens = [
        # post que vira evento (conciliável com o do Sympla acima)
        ("cultorockbar", "AAA111", "post", _post("AAA111", "Vem aí!")),
        ("cultorockbar", "AAA111", "extracao", EXTRACAO_OK),
        # só-Instagram: o caso Culto/Ordinário (nome sem par em plataforma)
        ("cultorockbar", "BBB222", "post", _post("BBB222", "Terça do pagode")),
        ("cultorockbar", "BBB222", "extracao",
         dict(EXTRACAO_OK, nome="Pagodin do Culto", preco=0.0, lineup=None)),
        # produtora: local vem do flyer; preco=true (LLM errou o tipo) não
        # pode virar lote de R$ 1 (bool é int em Python)
        ("produtoraxyz", "CCC333", "post", _post("CCC333", "Baile")),
        ("produtoraxyz", "CCC333", "extracao",
         dict(EXTRACAO_OK, nome="Baile da XYZ", local="Setor Comercial Sul",
              preco=True)),
        # guardas: nada disso vira evento
        ("cultorockbar", "DDD444", "post", _post("DDD444", "Foi demais!")),
        ("cultorockbar", "DDD444", "extracao",
         {"e_evento": False, "confianca": "alta"}),
        ("cultorockbar", "EEE555", "post", _post("EEE555", "Vem?")),
        ("cultorockbar", "EEE555", "extracao",
         dict(EXTRACAO_OK, confianca="media")),
        ("cultorockbar", "FFF666", "post", _post("FFF666", "Relembrando")),
        ("cultorockbar", "FFF666", "extracao",
         dict(EXTRACAO_OK, data="01/01/2020")),
        ("cultorockbar", "GGG777", "post", _post("GGG777", "Sem nome")),
        ("cultorockbar", "GGG777", "extracao", dict(EXTRACAO_OK, nome=None)),
        # post em COLABORAÇÃO: mesmo code em dois perfis no MESMO lote —
        # não pode quebrar o gravar (dedupe antes do executemany)
        ("produtoraxyz", "AAA111", "post", _post("AAA111", "Vem aí!")),
        # post ainda sem extração (fila da próxima rodada) e story: não derivam
        ("cultorockbar", "HHH888", "post", _post("HHH888", "Pendente")),
        ("cultorockbar", "III999", "story",
         {"code": "III999", "taken_at": TAKEN_AT,
          "expiring_at": TAKEN_AT + 86400}),
    ]
    store.gravar_instagram_raw(con, itens, raspado)

    derivar.aplicar(con)
    r = derivar.aplicar_instagram(con)
    assert r == {"eventos": 3, "lotes": 2, "descartados": 4}, r

    ev = con.execute("SELECT * FROM eventos WHERE id = 'instagram:AAA111'"
                     ).fetchone()
    assert ev["nome"] == "Alquimia Dark"
    assert ev["url"] == "https://www.instagram.com/p/AAA111/"
    assert ev["local_nome"] == "Culto Rock Bar", "casa: o local é a casa"
    assert ev["organizador"] == "Culto Rock Bar"
    assert ev["cidade"] == "Brasília" and ev["estado"] == "DF"
    assert ev["atracoes"] == "GABZ; VELOZZ"
    assert "[Do flyer]" in ev["descricao"] and "Vem aí!" in ev["descricao"]
    # 21:00 -03:00 normalizado p/ UTC na escrita (invariante do schema)
    esperado = (EM_10_DIAS.date() + timedelta(days=1)).isoformat()
    assert ev["start_date"] == f"{esperado}T00:00:00+00:00", ev["start_date"]
    # lote sintético + agregação
    lote = con.execute("SELECT * FROM lotes WHERE evento_id = "
                       "'instagram:AAA111'").fetchone()
    assert lote["nome"] == "entrada (do flyer)" and lote["preco"] == 20.0
    assert ev["preco_min"] == 20.0 and ev["tem_gratis"] == 0

    gratis = con.execute("SELECT preco_min, tem_gratis FROM eventos "
                         "WHERE id = 'instagram:BBB222'").fetchone()
    assert gratis["preco_min"] is None and gratis["tem_gratis"] == 1, \
        "preco 0 no flyer = evento grátis (lote grátis, sem lote pago)"
    prod = con.execute("SELECT local_nome, organizador, preco_min FROM eventos"
                       " WHERE id = 'instagram:CCC333'").fetchone()
    assert prod["local_nome"] == "Setor Comercial Sul", "produtora: local do flyer"
    assert prod["organizador"] == "Produtora XYZ"
    assert prod["preco_min"] is None, "preco=true (bool) virou lote"
    assert con.execute("SELECT COUNT(*) AS n FROM lotes WHERE evento_id = "
                       "'instagram:CCC333'").fetchone()["n"] == 0
    print("derivação: guarda, mapeamento, lote sintético, casa/produtora — ok")

    # idempotência (--so-derivar): re-derivar não duplica nem some
    derivar.aplicar(con)
    r2 = derivar.aplicar_instagram(con)
    assert r2 == r, "re-derivação mudou o resultado"
    n = con.execute("SELECT COUNT(*) AS n FROM eventos "
                    "WHERE fonte = 'instagram'").fetchone()["n"]
    assert n == 3
    print("derivação: idempotente (--so-derivar) — ok")

    # sumido: raspagem sem os posts na 1ª página NÃO condena a fonte instagram
    sumidos = atualizar._marcar_sumidos(
        con, {"sympla": {"coletados": 1}, "instagram": {"coletados": 1}},
        (AGORA + timedelta(hours=1)).isoformat())
    marcados = con.execute("SELECT id FROM eventos WHERE sumido = 1").fetchall()
    assert all(not m["id"].startswith("instagram:") for m in marcados), \
        f"instagram entrou na lógica de sumido: {marcados}"
    del sumidos

    # o sympla:111 sumiu de verdade (raspado_em antigo) — desfaz p/ a consulta
    con.execute("UPDATE eventos SET sumido = 0")
    con.commit()
    print("sumido: fonte instagram fora da lógica — ok")

    # conciliação via dedupe COM aliases: mesmo dia + nome ~0.7 + local
    # canonizado ("Culto" ↔ "Culto Rock Bar") → agrupa, canônico = sympla
    enriq = enriquecer.aplicar(con, aliases_local=instagram.aliases_local())
    grupo = con.execute("SELECT dedupe_grupo, dedupe_canonico FROM eventos "
                        "WHERE id = 'instagram:AAA111'").fetchone()
    assert grupo["dedupe_grupo"] == "sympla:111", (enriq["grupos"], dict(grupo))
    assert grupo["dedupe_canonico"] == 0
    # sem aliases o local não casa (nome sozinho não basta) → não agrupa —
    # prova que o elo da conciliação é a watchlist
    enriquecer.aplicar(con)
    grupo = con.execute("SELECT dedupe_grupo FROM eventos "
                        "WHERE id = 'instagram:AAA111'").fetchone()
    assert grupo["dedupe_grupo"] is None
    enriquecer.aplicar(con, aliases_local=instagram.aliases_local())
    print("conciliação: dedupe agrupa post ↔ Sympla via alias de local — ok")

    # consulta: canônico responde com o post em outras_urls; só-Instagram
    # aparece; detalhar mostra o lote do flyer; FTS acha pelo texto do flyer
    store.reconstruir_fts(con)
    achados = consulta.buscar_eventos(texto="alquimia")
    assert [e["url"] for e in achados] == ["https://sympla.com/alquimia"]
    assert "instagram.com/p/AAA111" in (achados[0]["outras_urls"] or "")
    pagode = consulta.buscar_eventos(texto="pagodin")
    assert [e["fonte"] for e in pagode] == ["instagram"]
    det = consulta.detalhar_evento("https://www.instagram.com/p/BBB222/")
    assert det["nome"] == "Pagodin do Culto"
    # FTS acha pelo texto que só existe no flyer (canônico só-Instagram)
    baile = consulta.buscar_eventos(texto="baile")
    assert any(e["url"].endswith("/p/CCC333/") for e in baile), baile
    det2 = consulta.detalhar_evento("https://www.instagram.com/p/AAA111/")
    assert det2["url"] == "https://sympla.com/alquimia", \
        "detalhar url do post deve responder o canônico (Sympla)"
    print("consulta: outras_urls, só-Instagram buscável, FTS no flyer — ok")

    con.close()


def main():
    test_datas()
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                     encoding="utf-8") as f:
        f.write(WATCHLIST_TESTE)
    tmp = f.name
    test_watchlist(tmp)
    # a derivação e o dedupe leem a watchlist de fixture, não a real
    instagram.WATCHLIST = Path(tmp)
    test_derivacao_e_consulta()
    print("\nOK — a fonte Instagram se comporta como a spec pede.")


if __name__ == "__main__":
    main()
