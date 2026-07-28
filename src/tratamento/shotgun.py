"""Tratamento do SHOTGUN: JSON-LD de `cru.shotgun` → colunas de
`tratado.eventos` e `tratado.lotes`.

Este arquivo sabe LER o Shotgun; `coleta/shotgun.py` sabe FALAR com ele — e é
só esse que conhece Playwright. Com o import do navegador no topo do módulo
antigo, ler um JSON-LD já gravado exigia a dependência inteira (spec §6.6).

O Shotgun tem uma origem só: o JSON-LD do catálogo já traz descrição, atrações,
organizador e preços, então ele não passa por descrever/precificar.
"""


def catalogo(p):
    """JSON-LD → colunas derivadas. `eventStatus` ausente não é 'não cancelado':
    é 'a fonte não disse', e por isso devolve {} em vez de 0."""
    status = p.get("eventStatus") or ""
    if not status:
        return {}
    return {"cancelado": 0 if status.endswith("EventScheduled") else 1}


def lotes(p):
    """JSON-LD: offers[] com name/price (TOTAL — a fonte não separa taxa)."""
    offers = p.get("offers") or []
    offers = [o for o in (offers if isinstance(offers, list) else [offers])
              if isinstance(o, dict)]
    saida = []
    for o in offers:
        preco = None
        for chave in ("lowPrice", "price"):
            try:
                preco = float(o[chave])
                break
            except (KeyError, TypeError, ValueError):
                continue
        saida.append({"nome": o.get("name"), "preco": preco, "taxa": None,
                      "gratis": preco == 0,
                      "esgotado": 1 if str(o.get("availability", ""))
                      .endswith("SoldOut") else 0})
    return saida


DERIVACOES = {"catalogo": catalogo}
LOTES = {"catalogo": lotes}
