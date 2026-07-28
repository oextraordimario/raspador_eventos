"""Enriquecimento de filmes via TMDB (NI-36): sinopse pt-BR, nota, ano.

Contrato próprio (não é fonte de catálogo — enriquece o que a grade da
Ingresso.com já trouxe): `raspar_filme(titulo, titulo_original)` devolve UM
payload com a consulta, os candidatos crus e o `escolhido` (ou None). Quem
grava é `gravar.gravar_cinema_extra` (Bronze acumulativa `cinema_extra_raw`,
fora do snapshot); quem aplica é `derivar.aplicar_cinema`.

Matching CONSERVADOR de propósito (spec 20260727_rework-pagina-cinema §4.3):
a chave de busca é o `originalTitle` da grade (fallback: título BR); só é
escolhido candidato cujo título normalizado casa EXATO com o buscado; entre
vários, o de lançamento mais recente que não seja futuro distante (filmes em
cartaz; retrospectiva de cult é o caso difícil — na dúvida, não grava, e o
payload guarda os candidatos para auditoria).

Auth: TMDB_API_KEY (v3, query param) via env/.env — nunca no repo. Termos do
TMDB exigem atribuição visível no produto (está no rodapé do site).
"""

import json
import string
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, timedelta

API = "https://api.themoviedb.org/3/search/movie"

# Quantos candidatos ficam gravados na Bronze (auditoria do matching).
MAX_CANDIDATOS = 5

# Candidato com lançamento além disso no futuro não é "em cartaz" (pré-venda
# longa existe; 6 meses cobre).
FUTURO_MAX_DIAS = 180


def _get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _normalizar(s):
    """Título comparável: minúsculo, sem acento, sem pontuação, espaço único."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.translate(str.maketrans("", "", string.punctuation))
    return " ".join(s.casefold().split())


def buscar_candidatos(consulta, api_key):
    """Busca no TMDB (pt-BR, região BR). Erro de rede sobe — o chamador
    registra e tenta de novo na próxima rodada."""
    qs = urllib.parse.urlencode({
        "query": consulta, "language": "pt-BR", "region": "BR",
        "include_adult": "false", "api_key": api_key,
    })
    return _get(f"{API}?{qs}").get("results") or []


def _escolher(candidatos, *consultas):
    """O candidato certo, ou None. Exige título normalizado IGUAL a alguma
    das consultas (title OU original_title); empate vai para o lançamento
    mais recente que não seja futuro distante. Sem match exato → None."""
    alvos = {_normalizar(c) for c in consultas if c}
    teto = (date.today() + timedelta(days=FUTURO_MAX_DIAS)).isoformat()
    exatos = [c for c in candidatos
              if {_normalizar(c.get("title")),
                  _normalizar(c.get("original_title"))} & alvos]
    validos = [c for c in exatos if (c.get("release_date") or "") <= teto]
    if not validos:
        return None
    return max(validos, key=lambda c: c.get("release_date") or "")


def raspar_filme(titulo, titulo_original, api_key):
    """Payload completo do matching de UM filme, para a Bronze.

    Busca pelo título ORIGINAL primeiro (é global e único; o BR muda de
    distribuidora pra distribuidora) e cai para o título BR se não render.
    """
    consultas, candidatos = [], []
    for consulta in dict.fromkeys(filter(None, [titulo_original, titulo])):
        consultas.append(consulta)
        candidatos = buscar_candidatos(consulta, api_key)
        if _escolher(candidatos, titulo, titulo_original):
            break
    escolhido = _escolher(candidatos, titulo, titulo_original)
    return {
        "consultas": consultas,
        "candidatos": candidatos[:MAX_CANDIDATOS],
        "escolhido": escolhido,   # None = sem match confiável (não gravar nota)
    }
