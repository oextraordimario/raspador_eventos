"""Raspador do Sympla via API interna de descoberta.

Descoberta em discover_sympla.py: o front do Sympla lista eventos chamando
  https://www.sympla.com.br/api/discovery-bff/search/category-type
que devolve JSON paginado {data, total, limit, page}. Sem navegador, sem HTML.

Parametros uteis:
  q         busca textual (ex.: "pagode")
  city      slug da cidade (ex.: "sao-paulo")
  state     UF (ex.: "SP")
  location  nome da cidade para exibicao (ex.: "São Paulo")
  limit     itens por pagina (usamos 100)
  page      pagina (1-based)

A API aceita ainda `only` (reduz o payload aos campos pedidos), mas NAO usamos:
a camada Bronze guarda o payload completo (~1,2 KB/evento), que e onde moram
campos como location.neighborhood e global_score — ver
docs/specs/20260710_camada-bronze/spec.md.
"""

import html
import re
import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://www.sympla.com.br/api/discovery-bff/search/category-type"

# BFF da pagina de evento (descoberto em 2026-07-09 interceptando XHR na pagina):
# devolve JSON com detail/strippedDetail (descricao), eventsCategory etc., sem auth
# e sem navegador. O id e o numerico no FIM da URL publica do evento (difere do id
# do catalogo!): .../evento/<slug>/3488482 -> 3488482.
BFF_EVENTO = "https://event-page.svc.sympla.com.br/api/event-bff/purchase/event/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Registro dos campos que _normalizar consome do catalogo. Ja foi o valor do
# parametro `only` da API; hoje a chamada vem sem `only` (payload completo, p/
# a camada Bronze) e a lista fica como documentacao do subconjunto mapeado.
CAMPOS = ("name,start_date,end_date,images,event_type,location,id,url,"
          "organizer,type")

# ID de tema do Sympla. 99 = "Festas e Shows" (vida noturna/musica), que e o
# recorte do PoC. Descoberto capturando a categoria show-musica-festa do site.
TEMA_FESTAS_SHOWS = 99


def _get_url(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Referer": "https://www.sympla.com.br/"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _get(params):
    qs = urllib.parse.urlencode(params, safe="/,")
    return _get_url(f"{API}?{qs}")


def _limpar_html(texto):
    """HTML -> texto puro (tags viram espaco, entidades resolvidas, espacos colapsados)."""
    if not texto:
        return None
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    return re.sub(r"\s+", " ", texto).strip() or None


def raspar_descricao(id_url):
    """Busca descricao (texto limpo) e categoria real de um evento no BFF da pagina.

    id_url: id numerico no fim da URL publica (ex.: 3488482). Retorna dict
    {"descricao", "categoria", "nome", "payload"} (descricao/categoria podem ser
    None); levanta excecao em erro de rede/HTTP — o chamador decide tolerar.
    "nome" e o nome que o BFF devolveu: o chamador DEVE conferi-lo contra o nome
    que ja tem, porque um id de outro namespace (ex.: Bileto) devolve outro
    evento valido sem erro HTTP (bug NI-17). "payload" e o JSON bruto, para a
    camada Bronze.
    """
    ev = _get_url(f"{BFF_EVENTO}{id_url}")
    cat = ev.get("eventsCategory")
    if isinstance(cat, dict):
        cat = cat.get("name")
    return {
        "descricao": _limpar_html(ev.get("detail")) or
                     _limpar_html(ev.get("strippedDetail")),
        "categoria": cat if isinstance(cat, str) and cat.strip() else None,
        "nome": ev.get("name"),
        "payload": ev,
    }


def raspar_tickets(id_url):
    """Busca os lotes/precos de um evento no BFF de tickets (mesmo id de pagina
    do raspar_descricao). Retorna {"payload": json bruto} para a camada Bronze;
    levanta excecao em erro de rede/HTTP.

    ATENCAO (NI-17): este endpoint NAO devolve o nome do evento, entao nao da
    para validar id trocado aqui. O chamador deve so pedir tickets de eventos
    cuja descricao ja passou na guarda de nome do _descrever.
    """
    return {"payload": _get_url(f"{BFF_EVENTO}{id_url}/tickets")}


def _normalizar(ev):
    loc = ev.get("location") or {}
    org = ev.get("organizer") or {}
    imgs = ev.get("images") or {}
    id_nativo = str(ev.get("id"))
    return {
        "id": f"sympla:{id_nativo}",
        "fonte": "sympla",
        "id_nativo": id_nativo,
        "nome": ev.get("name"),
        "start_date": ev.get("start_date"),
        "end_date": ev.get("end_date"),
        "cidade": loc.get("city") or None,
        "estado": loc.get("state") or None,
        "local_nome": loc.get("name") or None,
        "endereco": loc.get("address") or None,
        "lat": loc.get("lat") or None,
        "lon": loc.get("lon") or None,
        "categoria": ev.get("event_type") or None,
        "organizador": org.get("name") or None,
        "url": ev.get("url"),
        "imagem": imgs.get("lg") or imgs.get("original") or None,
        "raspado_em": datetime.now(timezone.utc).isoformat(),
        "_raw": ev,  # payload bruto -> eventos_raw (camada Bronze)
    }


def _futuro(ev):
    """True se o evento ainda nao terminou."""
    fim = ev.get("end_date") or ev.get("start_date")
    if not fim:
        return False
    try:
        return datetime.fromisoformat(fim) >= datetime.now(timezone.utc)
    except ValueError:
        return False


# Estatísticas da última chamada a raspar(), para o relatório de cobertura
# do atualizar.py (total_site = campo "total" reportado pela API).
ULTIMA_RASPAGEM = {}


def raspar(city="brasilia", state="DF", location="Brasília",
           tema=TEMA_FESTAS_SHOWS, q=None, max_paginas=10, pausa=1.0,
           apenas_futuros=True):
    """Raspa eventos de uma cidade (ou busca por texto) e devolve normalizados.

    tema: ID de tema do Sympla para filtrar categoria (default: festas/shows).
          Passe None para trazer todas as categorias.


    Retorna lista de dicts prontos para store.upsert_eventos.
    """
    vistos = {}
    for page in range(1, max_paginas + 1):
        params = {
            "service": "/v4/search",
            "city": city, "state": state, "location": location,
            "sort": "month-trending-score",
            "location_score": "month-trending-score",
            "limit": 100, "page": page,
        }
        if tema is not None:
            params["themes"] = tema
        if q:
            params["q"] = q
        resp = _get(params)
        data = resp.get("data") or []
        total = resp.get("total")
        if not data:
            break
        novos = 0
        for ev in data:
            norm = _normalizar(ev)
            if apenas_futuros and not _futuro(ev):
                continue
            if norm["id"] not in vistos:
                vistos[norm["id"]] = norm
                novos += 1
        print(f"  pagina {page}/{max_paginas}: +{len(data)} brutos "
              f"({novos} futuros novos) | total no site: {total} | "
              f"acumulado: {len(vistos)}")
        if len(data) < params["limit"]:
            break
        time.sleep(pausa)
    ULTIMA_RASPAGEM.update(total_site=total, coletados=len(vistos))
    return list(vistos.values())
