"""Teste executável do domínio cinema (NI-07): Bronze cinema_raw + snapshot,
derivação de filmes/sessoes, busca textual e camada de consulta/tools. Usa o
banco descartável eventos_teste no Neon (ver tests/base_teste.py).
Spec: docs/specs/20260711_raspagem-cinema/.

Uso: python tests/test_cinema.py
"""

import sys
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import consulta  # noqa: E402
import derivar  # noqa: E402
import store  # noqa: E402
from scrapers import cinema  # noqa: E402

import base_teste  # noqa: E402

base_teste.preparar()

AGORA_LOCAL = datetime.now(cinema.FUSO_BRASILIA)
HOJE = AGORA_LOCAL.date().isoformat()
ONTEM = (AGORA_LOCAL - timedelta(days=1)).date().isoformat()


def sessao(id_, horas_de_agora, tipos_display=("Dublado",), preco=30.0,
           sala="Sala 1"):
    quando = AGORA_LOCAL + timedelta(hours=horas_de_agora)
    types = [{"name": "Normal", "alias": "2D", "display": False}]
    types += [{"name": t, "display": True} for t in tipos_display]
    return {"id": id_, "price": preco, "room": sala, "types": types,
            "date": {"localDate": quando.isoformat()},
            "siteURL": f"https://checkout.ingresso.com/?sessionId={id_}"}


def filme(id_, titulo, generos, sessoes, **extra):
    m = {"id": id_, "title": titulo, "genres": generos, "duration": "100",
         "contentRating": "12 anos", "distributor": "X",
         "siteURL": f"https://www.ingresso.com/filme/{id_}",
         "images": [{"url": "http://poster", "type": "PosterPortrait"}],
         "trailers": [{"url": "http://trailer"}], "inPreSale": False,
         "rooms": [{"name": "Sala 1", "sessions": sessoes}]}
    m.update(extra)
    return m


def grade(dia, filmes):
    return [{"date": dia, "movies": filmes}]


def main():
    con = store.conectar()

    # ── derivação: payload no formato da API vira filmes + sessoes ──
    toy = filme("100", "Toy Story 5", ["Animação", "Aventura"],
                [sessao("s1", 5, ("Dublado",)),
                 sessao("s2", 8, ("3D", "XD", "Legendado"), preco=61.55)])
    # o MESMO filme no outro cinema: sessionIds próprios (como na API real),
    # filme único na Prata
    toy_no_park = filme("100", "Toy Story 5", ["Animação", "Aventura"],
                        [sessao("s5", 7, ("Dublado",))])
    drama = filme("200", "Um Drama Qualquer", ["Drama"],
                  # só o tipo display=False ("Normal") -> tipos cai no "2D"
                  [sessao("s3", 6, ())])
    passado = filme("300", "Filme De Ontem", ["Terror"],
                    [sessao("s4", -30)])  # única sessão já passou
    store.gravar_cinema_raw(con,
                            [("128", HOJE, grade(HOJE, [toy, drama])),
                             ("124", HOJE, grade(HOJE, [toy_no_park, passado]))],
                            "2026-01-01T00:00:00+00:00")
    r = derivar.aplicar_cinema(con)
    assert r == {"filmes": 3, "sessoes": 5}, r
    linhas = {s["id"]: s for s in con.execute("SELECT * FROM sessoes")}
    assert linhas["s2"]["tipos"] == "3D/XD/Legendado" and \
        linhas["s2"]["preco"] == 61.55, linhas["s2"]
    assert linhas["s3"]["tipos"] == "2D", "sem tipo exibível tinha que cair no 2D"
    assert linhas["s1"]["cinema"] == "Cinemark Pier 21"
    assert linhas["s5"]["cinema"] == "Kinoplex ParkShopping"
    assert linhas["s1"]["inicio"].endswith("+00:00"), \
        "inicio tinha que estar normalizado para UTC (invariante do schema)"
    print("derivação: filmes/sessoes do payload cru, tipos crus, UTC — ok")

    # ── busca textual: gêneros entram no tsvector (sem acento acha) ──
    store.reconstruir_fts(con)
    achados = consulta.buscar_filmes(texto="animacao")
    assert [f["titulo"] for f in achados] == ["Toy Story 5"], achados
    assert achados[0]["sessoes"] == 3 and "Pier 21" in achados[0]["cinemas"]
    print('busca: "animacao" acha "Animação"; agregado por filme — ok')

    # ── sessão passada some por padrão; filtro por cinema parcial ──
    titulos = {f["titulo"] for f in consulta.buscar_filmes()}
    assert "Filme De Ontem" not in titulos, "filme sem sessão futura vazou"
    so_pier = consulta.buscar_filmes(cinema="pier")
    assert {f["titulo"] for f in so_pier} == {"Toy Story 5", "Um Drama Qualquer"}
    print("consulta: esconde sessão passada; filtro por cinema parcial — ok")

    # ── sessoes_filme: por título parcial sem acento; erro claro ──
    d = consulta.sessoes_filme("toy story")
    assert d["id"] == "100" and len(d["sessoes"]) == 3, d
    assert d["sessoes"][0]["inicio"] <= d["sessoes"][-1]["inicio"]
    assert d["poster"] == "http://poster"
    assert "erro" in consulta.sessoes_filme("inexistente xyz")
    print("sessoes_filme: título parcial resolve; inexistente explica — ok")

    # ── snapshot: regravar cinema×dia substitui; dia passado é podado ──
    store.gravar_cinema_raw(con, [("999", ONTEM, grade(ONTEM, [drama]))],
                            "2026-01-01T00:00:00+00:00")
    store.gravar_cinema_raw(
        con, [("128", HOJE, grade(HOJE, [filme("100", "Toy Story 5",
                                               ["Animação"],
                                               [sessao("s9", 4)])])),
              ("124", HOJE, grade(HOJE, []))],
        "2026-01-02T00:00:00+00:00")
    r = derivar.aplicar_cinema(con)
    assert r == {"filmes": 1, "sessoes": 1}, (r, "snapshot tinha que substituir")
    ids = {s["id"] for s in con.execute("SELECT id FROM sessoes")}
    assert ids == {"s9"}, ids
    dias = {x["dia"] for x in con.execute("SELECT dia FROM cinema_raw")}
    assert ONTEM not in dias, "dia passado tinha que ser podado da Bronze"
    print("snapshot: grade nova substitui a anterior; poda dia passado — ok")

    # ── scraper: 404 = dia sem sessão (vazio); outro erro é registrado ──
    def get_404(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    original = cinema._get
    cinema._get = get_404
    assert cinema.sessoes_do_dia("1583", HOJE) == []

    def get_500(url):
        raise urllib.error.HTTPError(url, 500, "boom", None, None)
    cinema._get = get_500
    r = cinema.raspar(dias=1, pausa=0)
    assert r["raw"] == [] and len(r["erros"]) == len(cinema.CINEMAS), r
    assert cinema.ULTIMA_RASPAGEM == {"coletados": 0,
                                      "total_site": len(cinema.CINEMAS)}
    cinema._get = original
    print("scraper: 404 vira grade vazia; erro real vira registro — ok")

    con.close()
    print("\nTudo certo.")


if __name__ == "__main__":
    main()
