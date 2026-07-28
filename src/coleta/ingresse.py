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

from coleta import gravar

API = "https://api-site.ingresse.com/events/search"

# Endpoint de evento individual (no /openapi.json: "Get Event By Slug") — traz a
# descricao (HTML), que a busca nao retorna. Descoberto em 2026-07-09.
API_EVENTO = "https://api-site.ingresse.com/events/"

# Tickets/precos (descobertos em 2026-07-10 interceptando o embed de checkout,
# ver docs/specs/20260710_camada-prata/spec.md):
# - API_PUBLICO da as sessoes do evento, sem chave;
# - API_TICKETS da os lotes por sessao; a apikey e a PUBLICA do proprio front
#   (embutida no embedstore do site, nao e credencial de usuario).
API_PUBLICO = "https://event.ingresse.com/public/"
API_TICKETS = "https://api-embedstore.ingresse.com/api/v1/event/"
APIKEY_PUBLICA = "172f24fd2a903fc0647b61d7112ee1b9814702be"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
ISO_BRASILIA = "BRA-DF"


def _get_url(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Referer": "https://www.ingresse.com/"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _get(params):
    qs = urllib.parse.urlencode(params)
    return _get_url(f"{API}?{qs}")


def raspar_descricao(slug):
    """Busca o payload do evento pelo slug da URL publica (traz a descricao,
    que a busca nao retorna).

    Retorna {"nome", "payload"}; levanta excecao em erro de rede/HTTP — o
    chamador decide tolerar. Quem LE o payload e tratamento/ingresse.py.
    """
    ev = _get_url(f"{API_EVENTO}{urllib.parse.quote(slug)}")
    return {"nome": ev.get("title"), "payload": ev}


def raspar_tickets(id_nativo):
    """Busca os lotes/precos de um evento: resolve as sessoes no endpoint
    publico e tenta session/{primeira}/tickets; eventos "passaporte" respondem
    vazio por sessao — fallback para session/passports/tickets.

    Retorna {"payload": json bruto da resposta de tickets} para a camada
    Bronze; levanta excecao em erro de rede/HTTP.
    """
    pub = _get_url(f"{API_PUBLICO}{id_nativo}")
    sessoes = ((pub.get("data") or {}).get("sessions") or [])
    candidatos = [str(s["id"]) for s in sessoes if s.get("id")] or ["0"]
    for sessao in [candidatos[0], "passports"]:
        resp = _get_url(f"{API_TICKETS}{id_nativo}/session/{sessao}/tickets"
                        f"?apikey={APIKEY_PUBLICA}")
        if (resp.get("detail") or {}).get("responseData"):
            return {"payload": resp}
    return {"payload": resp}  # vazio mesmo: grava assim (fonte nao informou)


def _futuro(ev):
    session = ev.get("session") or {}
    quando = session.get("dateTime") or ev.get("event_date")
    if not quando:
        return False
    try:
        return datetime.fromisoformat(quando) >= datetime.now(timezone.utc)
    except ValueError:
        return False


# Estatísticas da última chamada a raspar(), para o relatório de cobertura
# do atualizar.py (total_site = pagination.total reportado pela API).
ULTIMA_RASPAGEM = {}


def raspar(iso_code=ISO_BRASILIA, title=None, max_paginas=10, tam=40,
           pausa=1.0, apenas_futuros=True):
    """Raspa eventos de uma localidade (ou busca por texto).

    Retorna registros de gravar.bruto() — payload cru, sem interpretacao.
    """
    vistos = {}
    pg = {}
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
            id_nativo = str(ev.get("id") or "")
            if id_nativo and id_nativo not in vistos:
                vistos[id_nativo] = gravar.bruto(id_nativo, ev)
                novos += 1
        print(f"  offset {page * tam}: +{len(data)} brutos ({novos} futuros "
              f"novos) | total no site: {pg.get('total')} | "
              f"acumulado: {len(vistos)}")
        if page + 1 >= (pg.get("total_pages") or 1):
            break
        time.sleep(pausa)
    ULTIMA_RASPAGEM.update(total_site=pg.get("total"), coletados=len(vistos))
    return list(vistos.values())
