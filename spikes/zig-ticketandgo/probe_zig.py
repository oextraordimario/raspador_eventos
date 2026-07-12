"""Probe determinístico: eventos de Brasília no Zig (zig.tickets).

Descoberta (2026-07-12, caçando nos chunks Next.js do site): o front consome a
API do SuperTicket (plataforma que a Zig incorporou), sem auth e sem navegador:

  GET https://ticket-api.superticket.com.br/events?per_page=50&page=N
      -> {"data": [eventos], "meta": {total, per_page, current_page, last_page}}
  GET https://ticket-api.superticket.com.br/events/{slug}
      -> detalhe (description HTML, event_location com nome do local, sectors)
  GET https://ticket-api.superticket.com.br/events/{id}/tickets
      -> lotes ("tickets"/"availables") — respondeu VAZIO em todos os testes

NÃO há filtro server-side de estado (by_state/uf/state são ignorados;
order_by_state=DF só reordena) — o catálogo nacional é pequeno (~250 eventos,
6 páginas de 50), então paginamos tudo e filtramos event_location.state == DF
do lado de cá.

Gera:
- resumo legível no stdout (eventos DF + detalhe de um deles)
- capturas/zig_catalogo_df.json (eventos DF do catálogo, payload bruto)
- capturas/zig_detalhe.json (UM detalhe bruto, referência de schema)

Uso: python spikes/zig-ticketandgo/probe_zig.py
"""

import json
import sys
import time
from pathlib import Path

import requests

API = "https://ticket-api.superticket.com.br"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
ESTADO = "DF"

AQUI = Path(__file__).parent
CAPTURAS = AQUI / "capturas"


def get(path, **params):
    r = requests.get(f"{API}/{path}", params=params, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def coletar():
    """Pagina o catálogo nacional e devolve só os eventos do DF (bruto)."""
    df, page = [], 1
    while True:
        d = get("events", per_page=50, page=page)
        eventos = d.get("data") or []
        meta = d.get("meta") or {}
        df += [e for e in eventos
               if (e.get("event_location") or {}).get("state") == ESTADO]
        print(f"  página {page}/{meta.get('last_page')}: {len(eventos)} eventos "
              f"| DF acumulado: {len(df)} | total no site: {meta.get('total')}",
              file=sys.stderr)
        if page >= (meta.get("last_page") or 1):
            break
        page += 1
        time.sleep(0.5)
    return df


if __name__ == "__main__":
    df = coletar()

    print(f"\n== {len(df)} eventos do {ESTADO} no catálogo do Zig ==")
    for e in df:
        loc = e.get("event_location") or {}
        print(f"- [{e['id']}] {e['name']}\n"
              f"    {e['start_date']} | {loc.get('city')}/{loc.get('state')} "
              f"| bairro: {loc.get('neighborhood')}\n"
              f"    https://zig.tickets/eventos/{e['slug']}")

    detalhe = None
    if df:
        detalhe = get(f"events/{df[0]['slug']}")
        loc = detalhe.get("event_location") or {}
        desc = (detalhe.get("description") or "").strip()
        print(f"\n== detalhe de \"{detalhe['name']}\" ==")
        print(f"  local: {loc.get('name')} | {loc.get('formatted_address')}")
        print(f"  descrição: {len(desc)} chars | has_sessions: "
              f"{detalhe.get('has_sessions')} | sectors: "
              f"{len(detalhe.get('event_sectors') or [])}")
        tickets = get(f"events/{df[0]['id']}/tickets")
        print(f"  /tickets: {json.dumps(tickets, ensure_ascii=False)[:200]}")

    CAPTURAS.mkdir(exist_ok=True)
    (CAPTURAS / "zig_catalogo_df.json").write_text(
        json.dumps(df, ensure_ascii=False, indent=2), encoding="utf-8")
    if detalhe:
        (CAPTURAS / "zig_detalhe.json").write_text(
            json.dumps(detalhe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nCapturas em {CAPTURAS}/zig_*.json")
