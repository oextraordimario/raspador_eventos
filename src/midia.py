"""Storage próprio de mídia (Vercel Blob) — NI-37.

Por que existe: hotlink de CDN alheio quebra sem aviso (o do Instagram
comprovadamente expira em horas; o da Ingresso.com pode passar a exigir
referer), e servir cópia própria com atribuição é a postura de ToS mais
defensável (anexo tos.md). Pôster de filme e flyer do Instagram usam esta
mesma infra.

Upload via REST do Vercel Blob, sem SDK: PUT no pathname com o token de
escrita. `x-add-random-suffix: 0` de propósito — pathname ESTÁVEL
(posters/<id>.webp, instagram/<code>.jpg), então re-subir substitui e a URL
é previsível. O token (BLOB_READ_WRITE_TOKEN) vem de env/.env — nunca do
repo. Sem token, os passos de upload são pulados com aviso (o front cai no
hotlink da fonte, o fallback declarado da spec §5).
"""

import json
import urllib.request

from store import env_var

API = "https://blob.vercel-storage.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# content-type → extensão do pathname (o que as fontes realmente servem)
EXTENSOES = {"image/webp": "webp", "image/jpeg": "jpg", "image/png": "png"}


def token():
    return env_var("BLOB_READ_WRITE_TOKEN")


def baixar(url):
    """Baixa a imagem da fonte. Devolve (bytes, content_type); erro sobe —
    o chamador registra e re-tenta na próxima rodada."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(), (r.headers.get_content_type() or
                          "application/octet-stream")


def subir(dados, pathname, content_type):
    """Sobe bytes para o Blob no pathname dado (público, cache de 1 ano —
    pôster e flyer não mudam depois de publicados). Devolve a URL pública."""
    req = urllib.request.Request(
        f"{API}/{pathname}", data=dados, method="PUT",
        headers={
            "Authorization": f"Bearer {token()}",
            "x-api-version": "7",
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
            "x-cache-control-max-age": "31536000",
        })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["url"]
