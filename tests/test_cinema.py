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

from servico import consulta  # noqa: E402
from tratamento import cinema as trat_cinema  # noqa: E402
from base import conexao
from coleta import gravar
from tratamento import busca
from tratamento import slug as trat_slug
from coleta import cinema  # noqa: E402

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
    m = {"id": id_, "title": titulo, "originalTitle": titulo,
         "genres": generos, "duration": "100",
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
    con = conexao.conectar()

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
    gravar.gravar_cinema_raw(con,
                            [("128", HOJE, grade(HOJE, [toy, drama])),
                             ("124", HOJE, grade(HOJE, [toy_no_park, passado]))],
                            "2026-01-01T00:00:00+00:00")
    r = trat_cinema.aplicar(con)
    assert r == {"filmes": 3, "sessoes": 5, "tmdb": 0}, r
    linhas = {s["id"]: s for s in con.execute("SELECT * FROM tratado.sessoes")}
    assert linhas["s2"]["tipos"] == "3D/XD/Legendado" and \
        linhas["s2"]["preco"] == 61.55, linhas["s2"]
    assert linhas["s3"]["tipos"] == "2D", "sem tipo exibível tinha que cair no 2D"
    assert linhas["s1"]["cinema"] == "Cinemark Pier 21"
    assert linhas["s5"]["cinema"] == "Kinoplex ParkShopping"
    assert linhas["s1"]["inicio"].endswith("+00:00"), \
        "inicio tinha que estar normalizado para UTC (invariante do schema)"
    print("derivação: filmes/sessoes do payload cru, tipos crus, UTC — ok")

    # ── busca textual: gêneros entram no tsvector (sem acento acha) ──
    trat_slug.aplicar(con)
    busca.reconstruir_fts(con)
    # commit explícito: desde a fatia 7 os passos do tratamento não
    # comitam sozinhos (o ciclo é uma transação só) e a consulta abre
    # a própria conexão.
    con.commit()
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

    # ── filtros do rework (NI-35): multi-valor, hora local, facetas ──
    assert achados[0]["poster"] == "http://poster", \
        "poster agora vem na lista (o card do site precisa dele)"
    dois = consulta.buscar_filmes(generos="Animação,Drama")
    assert {f["titulo"] for f in dois} == {"Toy Story 5", "Um Drama Qualquer"}
    assert consulta.buscar_filmes(generos="Terror") == [], \
        "gênero só de filme sem sessão futura tinha que voltar vazio"
    doze = consulta.buscar_filmes(classificacao="12 anos")
    assert {f["titulo"] for f in doze} == {"Toy Story 5", "Um Drama Qualquer"}
    assert consulta.buscar_filmes(classificacao="Livre") == []
    ambos = consulta.buscar_filmes(cinema="pier,park")
    assert {f["titulo"] for f in ambos} == {"Toy Story 5", "Um Drama Qualquer"}
    # janela de HORA LOCAL: s1 é agora+5h; a janela de 1h em volta dela pega
    # só ela (s5/s2 caem em horas distintas), inclusive cruzando a meia-noite
    h_s1 = (AGORA_LOCAL + timedelta(hours=5)).hour
    na_hora = consulta.buscar_filmes(hora_de=h_s1, hora_ate=(h_s1 + 1) % 24)
    toy_na_hora = [f for f in na_hora if f["id"] == "100"]
    assert toy_na_hora and toy_na_hora[0]["sessoes"] == 1, na_hora
    fac = consulta.facetas_filmes()
    assert fac["generos"] == ["Animação", "Aventura", "Drama"], fac
    assert fac["classificacoes"] == ["12 anos"], fac
    assert fac["cinemas"] == ["Cinemark Pier 21", "Kinoplex ParkShopping"], fac
    print("filtros novos: multi gênero/classificação, cinema CSV, hora local, "
          "facetas — ok")

    # ── sessoes_filme: por título parcial sem acento; erro claro ──
    d = consulta.sessoes_filme("toy story")
    assert d["id"] == "100" and len(d["sessoes"]) == 3, d
    assert d["sessoes"][0]["inicio"] <= d["sessoes"][-1]["inicio"]
    assert d["poster"] == "http://poster"
    assert d["cinemas"] == ["Cinemark Pier 21", "Kinoplex ParkShopping"], \
        "cinemas do filme são as opções do filtro da página"
    assert "erro" in consulta.sessoes_filme("inexistente xyz")
    print("sessoes_filme: título parcial resolve; inexistente explica — ok")

    # ── endereço público do filme (spec 20260729_urls-semanticas) ──
    # O card do site linka por `slug`, então ele tem que vir na busca; e o slug
    # tem que resolver o filme, senão a página de detalhe 404 no próprio link.
    porslug = {f["titulo"]: f["slug"] for f in consulta.buscar_filmes()}
    assert all(porslug.values()), f"filme sem slug na busca: {porslug}"
    assert porslug["Toy Story 5"] == "toy-story-5", porslug
    d_slug = consulta.sessoes_filme("toy-story-5")
    assert d_slug.get("id") == "100", d_slug.get("erro", d_slug.get("id"))
    # o ano vem do TMDB: sem ele o slug é curto, e quando ele chega o slug curto
    # tem que continuar resolvendo (o link compartilhado não pode morrer)
    con.execute("UPDATE tratado.filmes SET ano = 1999 WHERE id = '100'")
    trat_slug.aplicar(con)
    con.commit()
    assert consulta.sessoes_filme("toy-story-5").get("slug") == "toy-story-5-1999"
    print("slug: filme linkável por slug; slug curto resolve depois do ano — ok")

    # ── sessoes_filme com os filtros do rework: cinema/hora filtram as
    # sessões, mas `cinemas` (as OPÇÕES) segue sem filtro ──
    so_pier_d = consulta.sessoes_filme("100", cinema="pier")
    assert len(so_pier_d["sessoes"]) == 2 and \
        {s["cinema"] for s in so_pier_d["sessoes"]} == {"Cinemark Pier 21"}
    assert so_pier_d["cinemas"] == ["Cinemark Pier 21", "Kinoplex ParkShopping"]
    na_hora_d = consulta.sessoes_filme("100", hora_de=h_s1,
                                       hora_ate=(h_s1 + 1) % 24)
    assert len(na_hora_d["sessoes"]) == 1, na_hora_d["sessoes"]
    print("sessoes_filme: filtros de cinema/hora; opções não encolhem — ok")

    # ── enriquecimento externo (NI-36/NI-37): Bronze fora do snapshot ──
    gravar.gravar_tmdb(con, "100", {
        "consultas": ["Toy Story 5"],
        "candidatos": [],
        "escolhido": {"id": 552524, "title": "Toy Story 5",
                      "overview": "Buzz enfrenta a obsolescência.",
                      "release_date": "2026-06-17",
                      "vote_average": 7.4, "vote_count": 120},
    }, "2026-01-01T00:00:00+00:00")
    # o pôster no NOSSO storage não é payload de fonte: vai para operacao.midias
    gravar.gravar_midia(con, "100", "poster", "http://blob/p.webp",
                        "2026-01-01T00:00:00+00:00")
    gravar.gravar_tmdb(con, "200", {
        "consultas": ["Um Drama Qualquer"], "candidatos": [],
        "escolhido": None,   # matching não confiou: NÃO ganha nota
    }, "2026-01-01T00:00:00+00:00")
    r = trat_cinema.aplicar(con)
    assert r["tmdb"] == 1, r
    toy_f = con.execute("SELECT * FROM tratado.filmes WHERE id = '100'").fetchone()
    assert toy_f["sinopse"] == "Buzz enfrenta a obsolescência." and \
        toy_f["nota"] == 7.4 and toy_f["ano"] == 2026 and \
        toy_f["titulo_original"] == "Toy Story 5" and \
        toy_f["poster_proprio"] == "http://blob/p.webp", dict(toy_f)
    drama_f = con.execute("SELECT nota, sinopse FROM tratado.filmes "
                          "WHERE id = '200'").fetchone()
    assert drama_f["nota"] is None and drama_f["sinopse"] is None, \
        "sem match confiável não pode ganhar nota"
    print("extra: TMDB/pôster aplicados na derivação; sem match, sem nota — ok")

    # ── matching do TMDB é conservador (unit, sem rede) ──
    from coleta import tmdb
    certo = {"title": "Toy Story 5", "original_title": "Toy Story 5",
             "release_date": "2026-06-19", "id": 1}
    antigo = {"title": "Toy Story", "original_title": "Toy Story",
              "release_date": "1995-11-22", "id": 2}
    assert tmdb._escolher([antigo, certo], "Toy Story 5", None)["id"] == 1
    assert tmdb._escolher([antigo], "Toy Story 5", None) is None, \
        "parecido não é igual — na dúvida, não escolhe"
    futuro = {"title": "X", "original_title": "X",
              "release_date": "2099-01-01", "id": 3}
    assert tmdb._escolher([futuro], "X", None) is None, \
        "lançamento em futuro distante não é 'em cartaz'"
    intl = {"title": "A Odisséia!", "original_title": "The Odyssey",
            "release_date": "2026-07-01", "id": 4}
    assert tmdb._escolher([intl], "A Odisseia", "The Odyssey")["id"] == 4, \
        "acento/pontuação não podem atrapalhar o match"
    print("tmdb: match exato normalizado, sem chute — ok")

    # ── snapshot: regravar cinema×dia substitui; dia passado é podado ──
    gravar.gravar_cinema_raw(con, [("999", ONTEM, grade(ONTEM, [drama]))],
                            "2026-01-01T00:00:00+00:00")
    gravar.gravar_cinema_raw(
        con, [("128", HOJE, grade(HOJE, [filme("100", "Toy Story 5",
                                               ["Animação"],
                                               [sessao("s9", 4)])])),
              ("124", HOJE, grade(HOJE, []))],
        "2026-01-02T00:00:00+00:00")
    r = trat_cinema.aplicar(con)
    assert r == {"filmes": 1, "sessoes": 1, "tmdb": 1}, \
        (r, "snapshot tinha que substituir E re-aplicar o extra")
    ids = {s["id"] for s in con.execute("SELECT id FROM tratado.sessoes")}
    assert ids == {"s9"}, ids
    dias = {x["dia"] for x in con.execute("SELECT dia FROM cru.cinema")}
    assert ONTEM not in dias, "dia passado tinha que ser podado da Bronze"
    nota_pos = con.execute("SELECT nota FROM tratado.filmes WHERE id = '100'").fetchone()
    assert nota_pos["nota"] == 7.4, \
        "a nota do TMDB tem que SOBREVIVER à reconstrução do snapshot"
    print("snapshot: grade nova substitui; poda dia passado; extra sobrevive — ok")

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
