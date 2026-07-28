"""Teste executável das fontes novas Zig e Ticket and Go (NI-22): normalização
(datas locais → UTC na escrita, cidade rotulada, HTML limpo), filtro DF textual
do Ticket and Go, derivação de bairro (Zig) e de lotes com taxa fracionária
(Ticket and Go), e o efeito na consulta. Usa o banco descartável eventos_teste
no Neon (não toca a base de produção — ver tests/base_teste.py).
Spec: docs/specs/20260712_fontes-zig-ticketandgo/spec.md.

Uso: python tests/test_zig_ticketandgo.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import store  # noqa: E402
import derivar  # noqa: E402
import consulta  # noqa: E402
from scrapers import ticketandgo, zig  # noqa: E402

import base_teste  # noqa: E402

base_teste.preparar()

# Payloads de amostra, com a forma das capturas do spike (spikes/zig-ticketandgo/).
ZIG_CATALOGO = {
    "id": 22670, "name": "TURNÊ XAMÃ 2026 - Brasília",
    "slug": "turne-xama-2026-brasilia",
    "start_date": "2026-08-21T22:00:00.000-03:00",
    "end_date": "2026-08-22T04:00:00.000-03:00",
    "banner": "https://exemplo/banner.png", "thumb": None,
    "event_location": {"name": "Areninha Mané Garrincha", "zip_code": "70070-701",
                       "neighborhood": " Asa Norte ", "city": " Brasília",
                       "state": "DF", "lng": None, "lat": None,
                       "formatted_address": "Setor SRPN, 865 - Asa Norte, "
                                            "Brasília, DF - 70070-701"},
}

# Forma do GET /eventos/{slug}/evento (rota nova, NI-57): sem endereço, sem
# cidade/estado, sem lat/lon — só local, datas separadas e descrição HTML.
TNG_CATALOGO = {
    "id": 36999, "uuid": "x", "nome": "Pagode do Quadradinho - Arlindinho",
    "slug_evento": "pagode-do-quadradinho-arlindinho",
    "inicio": "2026-08-29", "hora_incio": "19:00:00",   # typo da própria fonte
    "fim": "2026-08-29", "hora_fim": "23:59:00",
    "local": "Brasília", "endereco": [],   # a fonte parou de expor endereço
    "nome_tipo_evento": "Evento", "banner": "https://exemplo/tng.png",
    "descricao": "<p><strong>PAGODE</strong> do bom &amp; barato</p>",
}

ZIG_TICKETS = {  # forma do pageProps.tickets do __NEXT_DATA__ (NI-23):
    # value em R$ + fee separada; esgotados vêm em unavailables[]
    "tickets": [
        {"id": 263110, "fee": 10.68, "value": 89, "public": 1,
         "name": "Geral [Infantil (6-12 anos)] Individual",
         "sector_name": "Geral"},
        {"id": 7, "fee": None, "value": 0, "public": 1,
         "name": "Cortesia", "sector_name": "Pista"},
        {"id": 8, "fee": 1, "value": 10, "public": 0,
         "name": "Lote oculto", "sector_name": "Geral"},
    ],
    "availables": [],
    "unavailables": [
        {"id": 263111, "fee": 32.28, "value": 269, "public": 1,
         "name": "Geral [Adulto - Meia Entrada] Individual",
         "sector_name": "Geral"},
    ],
}

TNG_TICKETS = {  # forma do GET /eventos/{slug} (data), capturada no spike:
    # lotes em bilhetes[] (evento simples) E em setores[].bilhetes[] (com setor)
    "taxa_conveniencia": 0.1,
    "bilhetes": [
        {"id": 1, "nome": "2° Lote - Ingresso", "valor": "60.0000",
         "valor_bilhete": "60.00"},
        {"id": 2, "nome": "Cortesia", "valor": "0.0000", "valor_bilhete": "0.00"},
    ],
    "setores": [
        {"nome": "Cabanas", "bilhetes": [
            {"id": 3, "nome": "Trust Love 14/07", "valor": "50.0000",
             "valor_bilhete": "50.00"},
        ]},
    ],
    "sessoes": [{"id": 28931, "nome": "Sessão 1",
                 "data_inicio": "2026-08-29 19:00:00"}],
}


def main():
    # --- Ticket and Go: filtro DF sem endereço (NI-57), casos REAIS medidos
    # contra os 79 eventos que a base tinha da era em que havia endereço ---
    # 1) local na lista curada (dados/locais_df.yaml)
    assert ticketandgo._do_df("Hípica Hall")
    assert ticketandgo._do_df("hipica hall")           # normalizado: sem acento/caixa
    # comparação é EXATA, não substring: a mesma igreja tem filial fora do DF
    assert ticketandgo._do_df("Comunidade das Nações - SIA")
    assert not ticketandgo._do_df("Comunidade das Nações São Paulo")
    # 2) termo inequívoco no local/nome
    assert ticketandgo._do_df("Taguatinga")
    assert ticketandgo._do_df("Arena BRB", "Festa em Brasília")
    # 3) CEP 70-73 ou DF na descrição (o sinal que cobre a maioria)
    assert ticketandgo._do_df("Caalex", "Trust Love",
                             "<p>SCEN Trecho 2, Brasília - DF, 70800-120</p>")
    assert ticketandgo._do_df("Projeted", "Master Fire", "📍 Distrito Federal – DF")
    # "Brasília" solto na descrição NÃO conta — caso real de Uberlândia:
    assert not ticketandgo._do_df(
        "Estádio Parque do Sabiá", "Legendários",
        "Endereço: Av. Constelação, 1175 - Jardim Brasília, Uberlândia - MG")
    # termos ambíguos com outras cidades ficam de fora de propósito
    assert not ticketandgo._do_df("Clube do Cruzeiro", "Festa", "Cruzeiro - SP")
    assert not ticketandgo._do_df("", None, None)
    print("ticketandgo: filtro DF por local curado + termo + CEP/UF na descrição — ok")

    # --- Ticket and Go: composição de data local (e robustez a variações) ---
    assert ticketandgo._quando("2026-08-29", "19:00:00") == \
        "2026-08-29T19:00:00-03:00"
    assert ticketandgo._quando("2026-08-29 19:00:00", None) == \
        "2026-08-29T19:00:00-03:00"  # data já com hora embutida
    assert ticketandgo._quando("2026-08-29", None) == \
        "2026-08-29T00:00:00-03:00"
    assert ticketandgo._quando(None, "19:00:00") is None
    print("ticketandgo: composição data+hora local -03:00 — ok")

    # --- normalização das duas fontes ---
    z = zig._normalizar(ZIG_CATALOGO)
    assert z["id"] == "zig:22670" and z["fonte"] == "zig"
    assert z["cidade"] == "Brasília", "trim do ' Brasília' da API"
    assert z["url"] == "https://zig.tickets/eventos/turne-xama-2026-brasilia"
    assert z["local_nome"] == "Areninha Mané Garrincha"
    assert zig._futuro(ZIG_CATALOGO)

    t = ticketandgo._normalizar(TNG_CATALOGO, "pagode-do-quadradinho-arlindinho",
                                "Brasília", "DF")
    assert t["id"] == "ticketandgo:36999", "id numérico do detalhe: chave estável"
    assert t["start_date"] == "2026-08-29T19:00:00-03:00"
    assert t["cidade"] == "Brasília" and t["estado"] == "DF", "rotulados pelo filtro"
    assert t["endereco"] is None and t["lat"] is None, "a fonte não expõe mais"
    assert t["descricao"] == "PAGODE do bom & barato", "HTML não foi limpo"
    assert t["url"] == ("https://www.ticketandgo.com.br/evento/"
                        "pagode-do-quadradinho-arlindinho")
    assert ticketandgo._futuro(TNG_CATALOGO)
    assert not ticketandgo._futuro({"inicio": "2020-01-01", "fim": None})
    # corte grosso do catálogo (só tem dia): margem de 1 dia p/ não perder
    # o evento que começa hoje à noite
    assert ticketandgo._futuro_por_dia({"inicio": "2030-01-01", "fim": None})
    assert not ticketandgo._futuro_por_dia({"inicio": "2020-01-01", "fim": None})
    assert not ticketandgo._futuro_por_dia({})
    print("normalização: zig e ticketandgo no schema unificado — ok")

    # --- escrita: datas locais viram ISO UTC comparável (invariante) ---
    con = store.conectar()
    store.upsert_eventos(con, [dict(z, _raw=ZIG_CATALOGO),
                               dict(t, _raw=TNG_CATALOGO)])
    r = con.execute("SELECT start_date FROM eventos "
                    "WHERE id = 'ticketandgo:36999'").fetchone()
    assert r["start_date"] == "2026-08-29T22:00:00+00:00", r["start_date"]
    r = con.execute("SELECT start_date FROM eventos "
                    "WHERE id = 'zig:22670'").fetchone()
    assert r["start_date"] == "2026-08-22T01:00:00+00:00", r["start_date"]
    print("escrita: -03:00 das duas fontes normalizado p/ UTC no upsert — ok")

    # --- derivação: bairro do Zig; lotes do Ticket and Go com taxa 10% ---
    store.gravar_raw(con, "ticketandgo:36999", "tickets", TNG_TICKETS,
                     "2026-07-12T00:00:00+00:00")
    store.gravar_raw(con, "zig:22670", "tickets", ZIG_TICKETS,
                     "2026-07-12T00:00:00+00:00")
    derivar.aplicar(con)
    r = con.execute("SELECT bairro FROM eventos WHERE id = 'zig:22670'").fetchone()
    assert r["bairro"] == "Asa Norte", r["bairro"]

    # lotes do Zig (NI-23): preco = value + fee; unavailables = esgotado;
    # public=0 não entra; sector_name só prefixa quando o nome não o traz
    lotes_zig = con.execute(
        "SELECT nome, preco, taxa, gratis, esgotado FROM lotes "
        "WHERE evento_id = 'zig:22670' ORDER BY ordem").fetchall()
    assert [dict(lt) for lt in lotes_zig] == [
        {"nome": "Geral [Infantil (6-12 anos)] Individual", "preco": 99.68,
         "taxa": 10.68, "gratis": 0, "esgotado": 0},
        {"nome": "Pista — Cortesia", "preco": 0.0, "taxa": None,
         "gratis": 1, "esgotado": 0},
        {"nome": "Geral [Adulto - Meia Entrada] Individual", "preco": 301.28,
         "taxa": 32.28, "gratis": 0, "esgotado": 1},
    ], [dict(lt) for lt in lotes_zig]
    r = con.execute("SELECT preco_min, tem_gratis, esgotado FROM eventos "
                    "WHERE id = 'zig:22670'").fetchone()
    assert dict(r) == {"preco_min": 99.68, "tem_gratis": 1, "esgotado": 0}, dict(r)
    lotes = con.execute("SELECT nome, preco, taxa, gratis, esgotado FROM lotes "
                        "WHERE evento_id = 'ticketandgo:36999' "
                        "ORDER BY ordem").fetchall()
    assert [dict(lt) for lt in lotes] == [
        {"nome": "2° Lote - Ingresso", "preco": 66.0, "taxa": 6.0,
         "gratis": 0, "esgotado": 0},   # 60 + 60×0.1 = total a pagar
        {"nome": "Cortesia", "preco": 0.0, "taxa": None,
         "gratis": 1, "esgotado": 0},
        {"nome": "Cabanas — Trust Love 14/07", "preco": 55.0, "taxa": 5.0,
         "gratis": 0, "esgotado": 0},   # aninhado em setores[].bilhetes[]
    ], [dict(lt) for lt in lotes]
    r = con.execute("SELECT preco_min, tem_gratis, esgotado FROM eventos "
                    "WHERE id = 'ticketandgo:36999'").fetchone()
    assert dict(r) == {"preco_min": 55.0, "tem_gratis": 1, "esgotado": 0}, dict(r)
    print("derivação: bairro (zig) e lotes c/ taxa fracionária (ticketandgo) — ok")

    # --- consulta: fontes novas aparecem; detalhar traz os lotes ---
    store.reconstruir_fts(con)
    achados = consulta.buscar_eventos(texto="pagode", limite=10)
    assert any(e["url"] == t["url"] for e in achados), achados
    todos = consulta.buscar_eventos(limite=50)
    assert {"zig", "ticketandgo"} <= {e["fonte"] for e in todos}
    det = consulta.detalhar_evento(t["url"])
    assert [lt["nome"] for lt in det["lotes"]] == \
        ["2° Lote - Ingresso", "Cortesia", "Cabanas — Trust Love 14/07"]
    print("consulta: fontes novas buscáveis; detalhar_evento com lotes — ok")

    con.close()
    print("\nOK — Zig e Ticket and Go se comportam como a spec do NI-22 pede.")


if __name__ == "__main__":
    main()
