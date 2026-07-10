"""Derivação a seco: (re)calcula colunas de eventos a partir do payload bruto.

Lê a camada Bronze (eventos_raw) e preenche as colunas derivadas de eventos —
sem nenhuma requisição de rede. Campo novo do schema vira uma função aqui e um
`python src/atualizar.py --so-derivar`, em vez de re-raspar tudo.

Idempotente como o enriquecer: cada execução reseta as colunas derivadas e
recalcula do zero a partir do bruto guardado.

Derivações (specs 20260710_camada-bronze e 20260710_camada-prata):
  (sympla, catalogo)  -> bairro, popularidade (global_score)
  (sympla, detalhe)   -> cancelado (campo cancelled do BFF)
  (sympla, tickets)   -> preco_min (R$; isFree -> 0), esgotado
  (ingresse, tickets) -> preco_min (R$), esgotado
  (shotgun, catalogo) -> preco_min (offers), esgotado, cancelado (eventStatus)

Derivações do mesmo evento nunca disputam coluna (cada origem preenche colunas
distintas), então a ordem de aplicação não importa.
"""

import json

# Colunas de eventos preenchidas por este módulo (resetadas a cada aplicar()).
# preco_min também é gravada pelo scraper do Shotgun no upsert; a derivação
# recalcula por cima e é a palavra final.
COLS_DERIVADAS = ["bairro", "popularidade", "esgotado", "cancelado", "preco_min"]


def _sympla_catalogo(p):
    bairro = ((p.get("location") or {}).get("neighborhood") or "").strip()
    score = p.get("global_score")
    return {"bairro": bairro or None,
            "popularidade": score if isinstance(score, (int, float)) else None}


def _sympla_detalhe(p):
    return {"cancelado": 1 if p.get("cancelled") else 0}


def _sympla_tickets(p):
    """Lotes do BFF de tickets: preço em reais no campo *.decimal."""
    lotes = [t for t in (p.get("tickets") or [])
             if isinstance(t, dict) and t.get("show") is not False]
    if not lotes:
        return {}
    precos = []
    for t in lotes:
        if t.get("isFree"):
            precos.append(0.0)
            continue
        for chave in ("salePriceWithDiscountMonetary", "salePriceMonetary"):
            v = (t.get(chave) or {}).get("decimal")
            if isinstance(v, (int, float)):
                precos.append(float(v))
                break
    return {"preco_min": min(precos) if precos else None,
            "esgotado": 1 if all((t.get("currentAvailableQty") or 0) == 0
                                 for t in lotes) else 0}


def _ingresse_tickets(p):
    """Lotes do embed de checkout: cada item tem type[] com price em reais."""
    itens = (p.get("detail") or {}).get("responseData") or []
    tipos = [tp for item in itens if isinstance(item, dict)
             for tp in (item.get("type") or [])
             if isinstance(tp, dict) and not tp.get("hidden")]
    if not tipos:
        return {}
    precos = [float(tp["price"]) for tp in tipos
              if isinstance(tp.get("price"), (int, float))]
    return {"preco_min": min(precos) if precos else None,
            "esgotado": 1 if all(tp.get("status") == "finished"
                                 for tp in tipos) else 0}


def _shotgun_catalogo(p):
    """JSON-LD: offers (preço/lotação) e eventStatus (cancelamento)."""
    offers = p.get("offers") or []
    offers = [o for o in (offers if isinstance(offers, list) else [offers])
              if isinstance(o, dict)]
    d = {}
    precos = []
    for o in offers:
        for chave in ("lowPrice", "price"):
            try:
                precos.append(float(o[chave]))
                break
            except (KeyError, TypeError, ValueError):
                continue
    if precos:
        d["preco_min"] = min(precos)
    if offers:
        d["esgotado"] = 1 if all(str(o.get("availability", "")).endswith("SoldOut")
                                 for o in offers) else 0
    status = p.get("eventStatus") or ""
    if status:
        d["cancelado"] = 0 if status.endswith("EventScheduled") else 1
    return d


# (fonte, origem) -> função payload -> {coluna: valor}; valor None é ignorado
# (não sobrescreve o que outra derivação tiver preenchido).
_DERIVACOES = {
    ("sympla", "catalogo"): _sympla_catalogo,
    ("sympla", "detalhe"): _sympla_detalhe,
    ("sympla", "tickets"): _sympla_tickets,
    ("ingresse", "tickets"): _ingresse_tickets,
    ("shotgun", "catalogo"): _shotgun_catalogo,
}


def aplicar(con):
    """Reseta e recalcula as colunas derivadas a partir de eventos_raw.

    Retorna {coluna: quantos eventos ganharam valor}, para o relatório.
    """
    con.execute("UPDATE eventos SET " +
                ", ".join(f"{c} = NULL" for c in COLS_DERIVADAS))
    contagem = dict.fromkeys(COLS_DERIVADAS, 0)
    rows = con.execute(
        "SELECT r.evento_id, r.origem, r.payload, e.fonte "
        "FROM eventos_raw r JOIN eventos e ON e.id = r.evento_id").fetchall()
    for r in rows:
        derivacao = _DERIVACOES.get((r["fonte"], r["origem"]))
        if not derivacao:
            continue
        campos = {c: v for c, v in derivacao(json.loads(r["payload"])).items()
                  if v is not None}
        if not campos:
            continue
        con.execute(
            "UPDATE eventos SET " + ", ".join(f"{c} = ?" for c in campos) +
            " WHERE id = ?", [*campos.values(), r["evento_id"]])
        for c in campos:
            contagem[c] += 1
    con.commit()
    return contagem
