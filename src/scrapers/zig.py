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

O endpoint de tickets (/events/{id}/tickets) respondeu vazio em todos os
testes do spike (o front manda params de sessão não mapeados); raspar_tickets
existe para documentá-lo, mas o pipeline NÃO o chama — preco_min do Zig fica
NULL ("fonte não informou"). Ver §3 da spec 20260712_fontes-zig-ticketandgo.
"""

import html
import re
import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

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


def _limpar_html(texto):
    """HTML -> texto puro (tags viram espaco, entidades resolvidas, espacos colapsados)."""
    if not texto:
        return None
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    return re.sub(r"\s+", " ", texto).strip() or None


def raspar_descricao(slug):
    """Busca a descricao (texto limpo) de um evento pelo slug da URL publica.

    Retorna dict {"descricao", "nome", "payload"} (descricao pode ser None —
    muitos eventos do Zig tem description vazia tipo "<p><br></p>"); levanta
    excecao em erro de rede/HTTP — o chamador decide tolerar. "nome" vai para
    a guarda uniforme de nome do _descrever (barata, mesmo sem namespace
    ambiguo conhecido como o Bileto/NI-17 do Sympla).
    """
    ev = _get_url(f"{API}/events/{urllib.parse.quote(slug)}")
    return {"descricao": _limpar_html(ev.get("description")),
            "nome": ev.get("name"),
            "payload": ev}  # JSON bruto, p/ a camada Bronze


def raspar_tickets(id_nativo):
    """Busca os lotes de um evento. ATENCAO: respondeu vazio em todos os
    testes do spike (o front manda params de sessao nao mapeados) — o
    pipeline NAO chama esta funcao; fica como documentacao do endpoint para
    quando o catalogo DF do Zig crescer (spec §3)."""
    return {"payload": _get_url(f"{API}/events/{id_nativo}/tickets")}


def _normalizar(ev):
    loc = ev.get("event_location") or {}
    id_nativo = str(ev.get("id"))
    slug = ev.get("slug")
    return {
        "id": f"zig:{id_nativo}",
        "fonte": "zig",
        "id_nativo": id_nativo,
        "nome": ev.get("name"),
        "start_date": ev.get("start_date"),
        "end_date": ev.get("end_date"),
        # a API manda " Brasília" com espaco na frente as vezes — trim
        "cidade": (loc.get("city") or "").strip() or None,
        "estado": (loc.get("state") or "").strip() or None,
        "local_nome": (loc.get("name") or "").strip() or None,
        "endereco": loc.get("formatted_address") or None,
        "lat": loc.get("lat") or None,
        "lon": loc.get("lng") or None,
        "categoria": None,  # o catalogo nao categoriza
        "organizador": None,  # so no detalhe (producer); nao vale a requisicao
        "url": f"https://zig.tickets/eventos/{slug}" if slug else None,
        "imagem": ev.get("banner") or ev.get("thumb")
                  or ev.get("vertical_banner") or None,
        "raspado_em": datetime.now(timezone.utc).isoformat(),
        "_raw": ev,  # payload bruto -> eventos_raw (camada Bronze)
    }


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
    """Pagina o catálogo nacional, filtra por estado e devolve normalizados.

    max_paginas é teto de segurança (o dobro das ~6 páginas observadas);
    o loop para sozinho em meta.last_page.
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
            norm = _normalizar(ev)
            if norm["id"] not in vistos:
                vistos[norm["id"]] = norm
                novos += 1
        print(f"  pagina {page}/{meta.get('last_page', '?')}: {len(data)} "
              f"brutos ({novos} futuros novos no {estado}) | total no site: "
              f"{meta.get('total')} | acumulado {estado}: {len(vistos)}")
        if page >= (meta.get("last_page") or 1):
            break
        time.sleep(pausa)
    ULTIMA_RASPAGEM.update(total_site=no_estado, coletados=len(vistos))
    return list(vistos.values())
