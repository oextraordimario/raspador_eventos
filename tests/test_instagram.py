"""Teste executável da fonte Instagram (spec 20260723_instagram-como-fonte,
v1 + v1.1): inferência de ano/hora da data do flyer, contrato de extração em
LISTA (agenda de carrossel → N eventos com sub-id e ?img_index), adaptador do
formato antigo de extração, guarda POR ITEM, lote sintético, exclusão da
lógica de sumido, dedupe intra-fonte (NI-01: agenda ↔ post individual e
"DEU BENZA" 3x) e conciliação cross-fonte via aliases. Sem rede pro Monid nem
pro claude -p — o que se testa é a derivação/integração, não os fornecedores
(camadas 2/3 da validação da spec). Usa o banco descartável eventos_teste no
Neon (ver tests/base_teste.py).

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
EM_12_DIAS = AGORA + timedelta(days=12)
EM_13_DIAS = AGORA + timedelta(days=13)
TAKEN_AT = int(AGORA.timestamp()) - 86400  # post de ontem


def _ddmm(dt):
    return f"{dt.day:02d}/{dt.month:02d}"


def _post(code, legenda, paginas=0):
    """Payload de post na forma da captura do spike (campos que usamos).
    paginas > 0 simula carrossel (media_type 8)."""
    p = {"code": code, "taken_at": TAKEN_AT, "media_type": 1,
         "caption": {"text": legenda, "hashtags": [], "mentions": []},
         "image_versions": {"items": [{"url": "https://cdn/expirada.jpg",
                                       "width": 1080}]}}
    if paginas:
        p["media_type"] = 8
        p["carousel_media"] = [
            {"image_versions": {"items": [{"url": f"https://cdn/p{n}.jpg"}]}}
            for n in range(1, paginas + 1)]
    return p


def _item(**kw):
    """Um item de evento no contrato v1.1 (defaults do caso feliz)."""
    base = {"nome": "Alquimia Dark", "data": _ddmm(EM_10_DIAS),
            "hora": "21:00", "preco": 20.0, "lineup": ["GABZ", "VELOZZ"],
            "local": None, "observacoes": "entrada 20$ na porta",
            "confianca": "alta"}
    base.update(kw)
    return base


def _ext(*itens):
    return {"eventos": list(itens)}


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


def test_contrato_e_fila():
    # urls_imagens: única, carrossel (ordem + teto) e vídeo sem imagem
    assert instagram.urls_imagens(_post("X", "a")) == ["https://cdn/expirada.jpg"]
    urls = instagram.urls_imagens(_post("X", "a", paginas=4))
    assert urls == [f"https://cdn/p{n}.jpg" for n in (1, 2, 3, 4)]
    assert len(instagram.urls_imagens(_post("X", "a", paginas=20))) == \
        instagram.MAX_PAGINAS_CARROSSEL, "teto de páginas"
    # fila de (re)extração: sem extração e formato antigo e_evento=false
    # re-extraem; formato antigo true e formato novo (mesmo vazio) não
    assert instagram.extracao_pendente(None)
    assert instagram.extracao_pendente({"e_evento": False, "confianca": "alta"})
    assert not instagram.extracao_pendente({"e_evento": True, "nome": "X"})
    assert not instagram.extracao_pendente({"eventos": []})
    assert not instagram.extracao_pendente({"eventos": [{"nome": "X"}]})
    print("contrato: urls do carrossel + fila de re-extração dirigida — ok")


def test_derivacao_e_consulta():
    con = store.conectar()
    raspado = AGORA.isoformat()
    start_10d = instagram.montar_start_date(_item(), TAKEN_AT)

    def _ev_plataforma(id_, nome, local, start=start_10d, fonte="sympla"):
        return {"id": id_, "fonte": fonte, "id_nativo": id_.split(":")[1],
                "nome": nome, "start_date": start, "end_date": None,
                "cidade": "Brasília", "estado": "DF", "local_nome": local,
                "endereco": "SCS Q 1", "lat": -15.8, "lon": -47.9,
                "categoria": "musica", "organizador": local,
                "url": f"https://sympla.com/{id_.split(':')[1]}",
                "imagem": "https://i/x.jpg", "raspado_em": raspado,
                "descricao": "Festa", "atracoes": None, "preco_min": None}

    # evento de plataforma pro dedupe cross-fonte conciliar: mesmo dia, nome
    # parecido (sim < 0.85 → precisa do local; alias "Culto" ↔ "Culto Rock
    # Bar" fecha) — e casos reais do NI-01 (intra-fonte)
    plataforma = [
        dict(_ev_plataforma("sympla:111", "Alquimia Dark - Edição Especial",
                            "Culto"), url="https://sympla.com/alquimia"),
        # "DEU BENZA" 3x na Arena CCB (caso real do NI-01): têm que agrupar
        _ev_plataforma("sympla:201", "DEU BENZA", "Arena CCB"),
        _ev_plataforma("sympla:202", "DEU BENZA", "Arena CCB"),
        _ev_plataforma("sympla:203", "DEU BENZA", "Arena CCB"),
        # contraexemplo: festas DISTINTAS da mesma casa no mesmo dia
        _ev_plataforma("sympla:301", "Feijuca do Ordi", "Ordinário Bar"),
        _ev_plataforma("sympla:302", "Noite do Rock Pesado", "Ordinário Bar"),
    ]
    store.upsert_eventos(con, plataforma)

    itens = [
        # post único que vira evento (conciliável com o sympla:111 acima)
        ("cultorockbar", "AAA111", "post", _post("AAA111", "Vem aí!")),
        ("cultorockbar", "AAA111", "extracao", _ext(_item())),
        # só-Instagram: o caso Culto/Ordinário (nome sem par em plataforma)
        ("cultorockbar", "BBB222", "post", _post("BBB222", "Terça do pagode")),
        ("cultorockbar", "BBB222", "extracao",
         _ext(_item(nome="Pagodin do Culto", preco=0.0, lineup=None))),
        # produtora: local vem do flyer; preco=true (LLM errou o tipo) não
        # pode virar lote de R$ 1 (bool é int em Python)
        ("produtoraxyz", "CCC333", "post", _post("CCC333", "Baile")),
        ("produtoraxyz", "CCC333", "extracao",
         _ext(_item(nome="Baile da XYZ", local="Setor Comercial Sul",
                    preco=True))),
        # formato ANTIGO (pré-v1.1): false não deriva; true deriva (adaptador)
        ("cultorockbar", "DDD444", "post", _post("DDD444", "Foi demais!")),
        ("cultorockbar", "DDD444", "extracao",
         {"e_evento": False, "confianca": "alta"}),
        ("cultorockbar", "OLD888", "post", _post("OLD888", "Formato antigo")),
        ("cultorockbar", "OLD888", "extracao",
         {"e_evento": True, "confianca": "alta", "nome": "Velho Formato Fest",
          "data": _ddmm(EM_10_DIAS), "hora": None, "preco": 15.0,
          "lineup": None, "local": None, "observacoes": None}),
        # guardas POR ITEM: nada disso vira evento
        ("cultorockbar", "EEE555", "post", _post("EEE555", "Vem?")),
        ("cultorockbar", "EEE555", "extracao",
         _ext(_item(confianca="media"))),
        ("cultorockbar", "FFF666", "post", _post("FFF666", "Relembrando")),
        ("cultorockbar", "FFF666", "extracao",
         _ext(_item(data="01/01/2020"))),
        ("cultorockbar", "GGG777", "post", _post("GGG777", "Sem nome")),
        ("cultorockbar", "GGG777", "extracao", _ext(_item(nome=None))),
        # CARROSSEL-AGENDA (v1.1): item 1 com data passada cai na guarda, mas
        # NÃO renumera os sobreviventes (posição na lista é o id)
        ("cultorockbar", "AGE999", "post",
         _post("AGE999", "Agenda da semana no Culto!", paginas=4)),
        ("cultorockbar", "AGE999", "extracao", _ext(
            _item(nome="Segunda da Saudade", data="01/01/2020", preco=None),
            _item(nome="Terça na Roda", data=_ddmm(EM_12_DIAS), preco=None,
                  lineup=["7naroda"]),
            _item(nome="Quarta de Bamba", data=_ddmm(EM_13_DIAS), preco=None,
                  lineup=None, hora=None),
            # dois eventos DISTINTOS no mesmo dia do mesmo carrossel, nomes
            # parecidos ("Terça na Roda" × "Terça no Samba" ≥ 0.55): a
            # extração já os separou — o dedupe NÃO pode colar (caso real:
            # "Samba Dona" × "Samba da Tia Zélia" na agenda mensal do Ordi)
            _item(nome="Terça no Samba", data=_ddmm(EM_12_DIAS), preco=None,
                  lineup=None))),
        # post individual do MESMO evento da agenda (padrão real: agenda na
        # terça + post no dia) — dedupe intra-fonte tem que colar os dois
        ("cultorockbar", "JJJ000", "post", _post("JJJ000", "Hoje é dia!")),
        ("cultorockbar", "JJJ000", "extracao",
         _ext(_item(nome="Quarta de Bamba com Breno",
                    data=_ddmm(EM_13_DIAS), preco=25.0, lineup=["Breno"]))),
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
    # eventos: AAA111, BBB222, CCC333, OLD888, AGE999:2/:3/:4, JJJ000
    # lotes: AAA111 (20), BBB222 (grátis), OLD888 (15), JJJ000 (25)
    # descartados (posts sem nenhum evento): DDD444, EEE555, FFF666, GGG777
    assert r == {"eventos": 8, "lotes": 4, "descartados": 4}, r

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
    velho = con.execute("SELECT nome, preco_min FROM eventos "
                        "WHERE id = 'instagram:OLD888'").fetchone()
    assert velho["nome"] == "Velho Formato Fest" and velho["preco_min"] == 15.0
    print("derivação: guarda por item, adaptador do formato antigo, lote — ok")

    # sub-eventos da agenda: id/posição estáveis (item 1 reprovado não
    # renumera) e URL com ?img_index (única, exigência do detalhar)
    ags = con.execute("SELECT id, nome, url FROM eventos WHERE id LIKE "
                      "'instagram:AGE999%' ORDER BY id").fetchall()
    assert [(a["id"], a["nome"]) for a in ags] == [
        ("instagram:AGE999:2", "Terça na Roda"),
        ("instagram:AGE999:3", "Quarta de Bamba"),
        ("instagram:AGE999:4", "Terça no Samba")], ags
    assert ags[0]["url"] == "https://www.instagram.com/p/AGE999/?img_index=2"
    print("agenda: N eventos por post, sub-id estável, ?img_index — ok")

    # idempotência (--so-derivar): re-derivar não duplica nem some
    derivar.aplicar(con)
    r2 = derivar.aplicar_instagram(con)
    assert r2 == r, "re-derivação mudou o resultado"
    n = con.execute("SELECT COUNT(*) AS n FROM eventos "
                    "WHERE fonte = 'instagram'").fetchone()["n"]
    assert n == 8
    print("derivação: idempotente (--so-derivar) — ok")

    # sumido: raspagem sem os posts na 1ª página NÃO condena a fonte instagram
    atualizar._marcar_sumidos(
        con, {"sympla": {"coletados": 1}, "instagram": {"coletados": 1}},
        (AGORA + timedelta(hours=1)).isoformat())
    marcados = con.execute("SELECT id FROM eventos WHERE sumido = 1").fetchall()
    assert all(not m["id"].startswith("instagram:") for m in marcados), \
        f"instagram entrou na lógica de sumido: {marcados}"
    con.execute("UPDATE eventos SET sumido = 0")  # sympla "sumiu" de mentira
    con.commit()
    print("sumido: fonte instagram fora da lógica — ok")

    # dedupe: cross-fonte via alias + intra-fonte (NI-01)
    enriq = enriquecer.aplicar(con, aliases_local=instagram.aliases_local())
    grupo = con.execute("SELECT dedupe_grupo, dedupe_canonico FROM eventos "
                        "WHERE id = 'instagram:AAA111'").fetchone()
    assert grupo["dedupe_grupo"] == "sympla:111", (enriq["grupos"], dict(grupo))
    assert grupo["dedupe_canonico"] == 0
    # NI-01: "DEU BENZA" 3x mesma casa/dia colapsa num grupo só
    benza = con.execute(
        "SELECT dedupe_grupo, dedupe_canonico FROM eventos WHERE id IN "
        "('sympla:201','sympla:202','sympla:203')").fetchall()
    assert len({b["dedupe_grupo"] for b in benza}) == 1 and \
        all(b["dedupe_grupo"] for b in benza), benza
    assert sum(b["dedupe_canonico"] for b in benza) == 1
    # contraexemplo: festas distintas da mesma casa no mesmo dia NÃO agrupam
    distintas = con.execute(
        "SELECT dedupe_grupo FROM eventos WHERE id IN "
        "('sympla:301','sympla:302')").fetchall()
    assert all(d["dedupe_grupo"] is None for d in distintas), distintas
    # agenda ↔ post individual: agrupa e o canônico é o INDIVIDUAL (tem o
    # preço do flyer → completude com preco_min, spec §8.4)
    par = {r_["id"]: dict(r_) for r_ in con.execute(
        "SELECT id, dedupe_grupo, dedupe_canonico FROM eventos WHERE id IN "
        "('instagram:AGE999:3','instagram:JJJ000')")}
    assert par["instagram:AGE999:3"]["dedupe_grupo"] == "instagram:JJJ000", par
    assert par["instagram:JJJ000"]["dedupe_canonico"] == 1
    assert par["instagram:AGE999:3"]["dedupe_canonico"] == 0
    # sub-eventos do MESMO post nunca colam entre si (mesmo dia + nomes ≥0.55)
    mesmo_post = con.execute(
        "SELECT id, dedupe_grupo FROM eventos WHERE id IN "
        "('instagram:AGE999:2','instagram:AGE999:4')").fetchall()
    assert all(m["dedupe_grupo"] is None for m in mesmo_post), mesmo_post
    print("dedupe: NI-01 (DEU BENZA, agenda ↔ post do dia) + cross-fonte — ok")

    # consulta: canônico responde com o post em outras_urls; só-Instagram
    # aparece; detalhar mostra o lote do flyer; FTS acha texto do flyer
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
    # FTS acha pela CASA (local_nome/organizador indexados na v1.1): "o que
    # tem no Ordinário?" não pode depender da legenda citar o nome completo
    por_local = consulta.buscar_eventos(texto="comercial")
    assert any(e["url"].endswith("/p/CCC333/") for e in por_local), por_local
    det2 = consulta.detalhar_evento("https://www.instagram.com/p/AAA111/")
    assert det2["url"] == "https://sympla.com/alquimia", \
        "detalhar url do post deve responder o canônico (Sympla)"
    # detalhar a linha da agenda responde o canônico (o post individual)
    det3 = consulta.detalhar_evento(
        "https://www.instagram.com/p/AGE999/?img_index=3")
    assert det3["url"] == "https://www.instagram.com/p/JJJ000/", det3["url"]
    assert [lt["preco"] for lt in det3["lotes"]] == [25.0]
    print("consulta: outras_urls, só-Instagram, agenda → canônico, FTS — ok")

    con.close()


def main():
    test_datas()
    test_contrato_e_fila()
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                     encoding="utf-8") as f:
        f.write(WATCHLIST_TESTE)
    tmp = f.name
    test_watchlist(tmp)
    # a derivação e o dedupe leem a watchlist de fixture, não a real
    instagram.WATCHLIST = Path(tmp)
    test_derivacao_e_consulta()
    print("\nOK — a fonte Instagram (v1 + v1.1) se comporta como a spec pede.")


if __name__ == "__main__":
    main()
