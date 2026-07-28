"""Raspador do Zig (zig.tickets) via API interna do SuperTicket.

Descoberta (spike spikes/zig-ticketandgo/, 2026-07-12): o site é Next.js e o
front consome a API do SuperTicket — plataforma que a Zig incorporou — sem
autenticação e sem navegador:

  GET https://ticket-api.superticket.com.br/events?per_page=50&page=N
      -> {"data": [eventos], "meta": {total, last_page, ...}}
  GET https://ticket-api.superticket.com.br/events/{slug}
      -> detalhe (description HTML, event_location.name, producer)

NÃO há filtro server-side de estado (by_state/uf/state são ignorados) — o
catálogo nacional é pequeno (~250 eventos, ~6 páginas), então paginamos tudo
e filtramos event_location.state do lado de cá.

Tickets/preços (NI-23, resolvido em 2026-07-12): o endpoint JSON
/events/{id}/tickets responde vazio sem códigos opcionais do front (d/s), mas
a PÁGINA pública do evento é SSR e embute o payload completo de tickets no
__NEXT_DATA__ (pageProps.tickets: value em R$, fee separada ~12%, esgotados
em unavailables) — raspar_tickets lê de lá, ainda por HTTP puro, sem
navegador. Ver spec 20260712_fontes-zig-ticketandgo §2.
"""

import re
import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from coleta import gravar

API = "https://ticket-api.superticket.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _get_url(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Referer": "https://zig.tickets/"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def raspar_descricao(slug):
    """Busca o payload do evento pelo slug da URL publica (traz a description).

    Retorna {"nome", "payload"}; levanta excecao em erro de rede/HTTP — o
    chamador decide tolerar. Quem LE o payload e tratamento/zig.py.

    "nome" vai para a guarda uniforme de nome do _descrever (barata, mesmo sem
    namespace ambiguo conhecido como o Bileto/NI-17 do Sympla).
    """
    ev = _get_url(f"{API}/events/{urllib.parse.quote(slug)}")
    return {"nome": ev.get("name"), "payload": ev}


_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def raspar_tickets(slug):
    """Busca os lotes/precos de um evento no __NEXT_DATA__ da PAGINA publica
    (o SSR embute pageProps.tickets; o endpoint JSON /events/{id}/tickets
    responde vazio sem codigos opcionais do front — NI-23). HTTP puro.

    Retorna {"payload": dict de tickets, "nome": nome do evento na pagina}
    — o chamador DEVE conferir o nome (guarda uniforme contra pagina
    trocada/redirecionada, mesmo padrao do descrever). Levanta excecao em
    erro de rede/HTTP ou se a pagina vier sem __NEXT_DATA__ (layout mudou).
    """
    req = urllib.request.Request(
        f"https://zig.tickets/eventos/{urllib.parse.quote(slug)}",
        headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pagina = r.read().decode("utf-8", "replace")
    m = _NEXT_DATA_RE.search(pagina)
    if not m:
        raise ValueError("pagina do evento sem __NEXT_DATA__ (layout mudou?)")
    props = (json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}
    return {"payload": props.get("tickets") or {},
            "nome": (props.get("event") or {}).get("name")}


def _futuro(ev):
    fim = ev.get("end_date") or ev.get("start_date")
    if not fim:
        return False
    try:
        return datetime.fromisoformat(fim) >= datetime.now(timezone.utc)
    except ValueError:
        return False


# Estatísticas da última chamada a raspar(), para o relatório de cobertura do
# atualizar.py (total_site = eventos do ESTADO no catálogo — o recorte, não o
# total nacional, que leria como scraper quebrado).
ULTIMA_RASPAGEM = {}


def raspar(estado="DF", per_page=50, max_paginas=12, pausa=0.5,
           apenas_futuros=True):
    """Pagina o catálogo nacional e filtra por estado.

    max_paginas é teto de segurança (o dobro das ~6 páginas observadas);
    o loop para sozinho em meta.last_page. Retorna registros de gravar.bruto().
    """
    vistos, no_estado = {}, 0
    for page in range(1, max_paginas + 1):
        qs = urllib.parse.urlencode({"per_page": per_page, "page": page})
        resp = _get_url(f"{API}/events?{qs}")
        data = resp.get("data") or []
        meta = resp.get("meta") or {}
        novos = 0
        for ev in data:
            if ((ev.get("event_location") or {}).get("state") or "").strip() \
                    != estado:
                continue
            no_estado += 1
            if apenas_futuros and not _futuro(ev):
                continue
            id_nativo = str(ev.get("id") or "")
            if id_nativo and id_nativo not in vistos:
                vistos[id_nativo] = gravar.bruto(id_nativo, ev)
                novos += 1
        print(f"  pagina {page}/{meta.get('last_page', '?')}: {len(data)} "
              f"brutos ({novos} futuros novos no {estado}) | total no site: "
              f"{meta.get('total')} | acumulado {estado}: {len(vistos)}")
        if page >= (meta.get("last_page") or 1):
            break
        time.sleep(pausa)
    ULTIMA_RASPAGEM.update(total_site=no_estado, coletados=len(vistos))
    return list(vistos.values())
