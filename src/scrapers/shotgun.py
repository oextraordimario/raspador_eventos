"""Raspador do Shotgun (shotgun.live).

Diferente de Sympla e Ingresse, o Shotgun bloqueia HTTP puro (responde 429) e
renderiza os eventos via React Server Components — não há API JSON interna
simples de chamar. A técnica que funciona:

  1. Carregar a página da cidade num navegador real (Playwright) e extrair os
     slugs dos eventos (links /events/<slug>).
  2. Para cada evento, carregar a página e ler o JSON-LD (schema.org/MusicEvent),
     que traz nome, datas e local de forma estruturada e estável.

Observação de produto: o Shotgun é uma plataforma internacional focada em vida
noturna. O catálogo em Brasília é modesto (dezenas de eventos), mas existe —
sambas, festas e shows. O addressLocality do JSON-LD costuma vir com o bairro
(ex.: "Asa Sul"), não a cidade; como raspamos a página de uma cidade específica,
rotulamos cidade/estado a partir do parâmetro de busca para manter a base
consultável por cidade.
"""

import re
import json
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

BASE = "https://shotgun.live"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _extrair_musicevent(html):
    """Retorna o primeiro bloco JSON-LD do tipo MusicEvent/Event, ou None."""
    for bloco in _LD_RE.findall(html):
        try:
            obj = json.loads(bloco)
        except ValueError:
            continue
        for it in (obj if isinstance(obj, list) else [obj]):
            tipo = it.get("@type")
            tipos = tipo if isinstance(tipo, list) else [tipo]
            if any(t in ("MusicEvent", "Event", "Festival", "SocialEvent")
                   for t in tipos):
                return it
    return None


def _normalizar(ld, slug, cidade_label, estado_label):
    loc = ld.get("location") or {}
    addr = loc.get("address") or {}
    # addressLocality do Shotgun costuma ser o bairro; guardamos como bairro e
    # usamos o rotulo da cidade pesquisada para o campo cidade (consultavel).
    bairro = addr.get("addressLocality") or None
    return {
        "id": f"shotgun:{slug}",
        "fonte": "shotgun",
        "id_nativo": slug,
        "nome": ld.get("name"),
        "start_date": ld.get("startDate"),
        "end_date": ld.get("endDate"),
        "cidade": cidade_label,
        "estado": estado_label,
        "local_nome": loc.get("name") or bairro,
        "endereco": bairro or addr.get("streetAddress") or None,
        "lat": (loc.get("geo") or {}).get("latitude") or None,
        "lon": (loc.get("geo") or {}).get("longitude") or None,
        "categoria": "MusicEvent",
        "organizador": None,
        "url": ld.get("url") or f"{BASE}/en/events/{slug}",
        "imagem": ld.get("image") if isinstance(ld.get("image"), str) else None,
        "raspado_em": datetime.now(timezone.utc).isoformat(),
    }


def _futuro(ld):
    quando = ld.get("endDate") or ld.get("startDate")
    if not quando:
        return False
    try:
        return datetime.fromisoformat(quando.replace("Z", "+00:00")) >= \
            datetime.now(timezone.utc)
    except ValueError:
        return False


def raspar(city_slug="brasilia", cidade_label="Brasília", estado_label="DF",
           max_eventos=40, apenas_futuros=True):
    """Raspa eventos de uma cidade no Shotgun e normaliza para o schema unificado."""
    eventos = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="pt-BR")
        page = ctx.new_page()

        page.goto(f"{BASE}/pt/cities/{city_slug}", wait_until="networkidle",
                  timeout=60000)
        for _ in range(3):
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(1200)
        slugs = sorted(set(re.findall(r'/events/([a-z0-9-]+)', page.content())))
        print(f"  {len(slugs)} eventos encontrados em '{city_slug}'")

        for slug in slugs[:max_eventos]:
            try:
                page.goto(f"{BASE}/en/events/{slug}", wait_until="domcontentloaded",
                          timeout=45000)
                ld = _extrair_musicevent(page.content())
            except Exception:
                ld = None
            if not ld:
                continue
            if apenas_futuros and not _futuro(ld):
                continue
            eventos.append(_normalizar(ld, slug, cidade_label, estado_label))

        browser.close()
    print(f"  {len(eventos)} eventos futuros normalizados")
    return eventos
