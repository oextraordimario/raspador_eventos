"""Raspador do Sympla via API interna de descoberta.

Descoberta em discover_sympla.py: o front do Sympla lista eventos chamando
  https://www.sympla.com.br/api/discovery-bff/search/category-type
que devolve JSON paginado {data, total, limit, page}. Sem navegador, sem HTML.

Parametros uteis:
  q         busca textual (ex.: "pagode")
  city      slug da cidade (ex.: "sao-paulo")
  state     UF (ex.: "SP")
  location  nome da cidade para exibicao (ex.: "São Paulo")
  only      campos retornados (reduz payload)
  limit     itens por pagina (usamos 100)
  page      pagina (1-based)
"""

import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://www.sympla.com.br/api/discovery-bff/search/category-type"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CAMPOS = ("name,start_date,end_date,images,event_type,location,id,url,"
          "organizer,type")

# ID de tema do Sympla. 99 = "Festas e Shows" (vida noturna/musica), que e o
# recorte do PoC. Descoberto capturando a categoria show-musica-festa do site.
TEMA_FESTAS_SHOWS = 99


def _get(params):
    qs = urllib.parse.urlencode(params, safe="/,")
    req = urllib.request.Request(
        f"{API}?{qs}",
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Referer": "https://www.sympla.com.br/"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


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
            "only": CAMPOS, "sort": "month-trending-score",
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
    return list(vistos.values())
