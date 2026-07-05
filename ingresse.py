"""Raspador do Ingresse via API interna do site (api-site.ingresse.com).

Descoberta: o site é Next.js SSR; a API de descoberta é o BFF
api-site.ingresse.com, um serviço FastAPI que expõe o schema em /openapi.json
(sem autenticação). O endpoint de busca é:
  https://api-site.ingresse.com/events/search
Parâmetros (do openapi.json):
  iso_code   localidade no formato "BRA-DF" (Distrito Federal) etc.
  title      busca textual
  date_from  / date_to   janela de datas
  size       itens por página
  offset     deslocamento (paginação)

O catálogo do Ingresse em Brasília é pequeno e já focado em vida noturna
(categorias: festivais, samba-e-pagode, shows), então não é preciso filtrar
categoria como no Sympla.
"""

import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api-site.ingresse.com/events/search"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
ISO_BRASILIA = "BRA-DF"


def _get(params):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{API}?{qs}",
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Referer": "https://www.ingresse.com/"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _normalizar(ev):
    place = ev.get("place") or {}
    geo = place.get("location") or {}
    poster = ev.get("poster") or ev.get("images") or {}
    session = ev.get("session") or {}
    id_nativo = str(ev.get("id"))
    quando = session.get("dateTime") or ev.get("event_date")
    return {
        "id": f"ingresse:{id_nativo}",
        "fonte": "ingresse",
        "id_nativo": id_nativo,
        "nome": ev.get("title"),
        "start_date": quando,
        "end_date": None,  # a busca não retorna término
        "cidade": place.get("city") or None,
        "estado": place.get("state") or None,
        "local_nome": place.get("name") or None,
        "endereco": place.get("street") or None,
        "lat": geo.get("lat") or None,
        "lon": geo.get("lon") or None,
        "categoria": None,
        "organizador": None,  # não vem no resultado de busca
        "url": f"https://www.ingresse.com/{ev.get('slug')}" if ev.get("slug") else None,
        "imagem": poster.get("large") or poster.get("medium") or None,
        "raspado_em": datetime.now(timezone.utc).isoformat(),
    }


def _futuro(ev):
    session = ev.get("session") or {}
    quando = session.get("dateTime") or ev.get("event_date")
    if not quando:
        return False
    try:
        return datetime.fromisoformat(quando) >= datetime.now(timezone.utc)
    except ValueError:
        return False


def raspar(iso_code=ISO_BRASILIA, title=None, max_paginas=10, tam=40,
           pausa=1.0, apenas_futuros=True):
    """Raspa eventos de uma localidade (ou busca por texto) e normaliza."""
    vistos = {}
    for page in range(max_paginas):
        params = {"iso_code": iso_code, "size": tam, "offset": page * tam}
        if title:
            params["title"] = title
        resp = _get(params)
        data = resp.get("events") or []
        pg = resp.get("pagination") or {}
        if not data:
            break
        novos = 0
        for ev in data:
            if apenas_futuros and not _futuro(ev):
                continue
            norm = _normalizar(ev)
            if norm["id"] not in vistos:
                vistos[norm["id"]] = norm
                novos += 1
        print(f"  offset {page * tam}: +{len(data)} brutos ({novos} futuros "
              f"novos) | total no site: {pg.get('total')} | "
              f"acumulado: {len(vistos)}")
        if page + 1 >= (pg.get("total_pages") or 1):
            break
        time.sleep(pausa)
    return list(vistos.values())
