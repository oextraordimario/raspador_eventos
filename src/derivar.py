"""Derivação a seco: (re)calcula colunas de eventos e a tabela de lotes a
partir do payload bruto.

Lê a camada Bronze (eventos_raw) e preenche as colunas derivadas de eventos e
a tabela lotes — sem nenhuma requisição de rede. Campo novo do schema vira uma
função aqui e um `python src/atualizar.py --so-derivar`, em vez de re-raspar.

Idempotente como o enriquecer: cada execução reseta as colunas derivadas,
apaga os lotes e recalcula do zero a partir do bruto guardado.

Derivações diretas (specs 20260710_camada-bronze e 20260710_camada-prata):
  (sympla, catalogo)  -> bairro, popularidade (global_score)
  (sympla, detalhe)   -> cancelado (campo cancelled do BFF)
  (shotgun, catalogo) -> cancelado (eventStatus)

Lotes de ingresso (spec 20260710_lotes-ingressos):
  (sympla, tickets), (ingresse, tickets), (shotgun, catalogo) -> tabela lotes,
  com preco normalizado como TOTAL a pagar (Sympla já embute a taxa; Ingresse
  soma price+tax). preco_min/esgotado/tem_gratis de eventos são AGREGAÇÕES dos
  lotes: preco_min = menor lote PAGO (cortesia não mascara mais o preço real),
  tem_gratis = há lote grátis não esgotado, esgotado = todos os lotes esgotados.

Derivações do mesmo evento nunca disputam coluna (cada origem preenche colunas
distintas), então a ordem de aplicação não importa.
"""

import json

# Colunas de eventos preenchidas por este módulo (resetadas a cada aplicar()).
# preco_min também é gravada pelo scraper do Shotgun no upsert; a derivação
# recalcula por cima e é a palavra final.
COLS_DERIVADAS = ["bairro", "popularidade", "esgotado", "cancelado",
                  "preco_min", "tem_gratis"]


def _sympla_catalogo(p):
    bairro = ((p.get("location") or {}).get("neighborhood") or "").strip()
    score = p.get("global_score")
    return {"bairro": bairro or None,
            "popularidade": score if isinstance(score, (int, float)) else None}


def _sympla_detalhe(p):
    return {"cancelado": 1 if p.get("cancelled") else 0}


def _shotgun_catalogo(p):
    status = p.get("eventStatus") or ""
    if not status:
        return {}
    return {"cancelado": 0 if status.endswith("EventScheduled") else 1}


# (fonte, origem) -> função payload -> {coluna: valor}; valor None é ignorado
# (não sobrescreve o que outra derivação tiver preenchido).
_DERIVACOES = {
    ("sympla", "catalogo"): _sympla_catalogo,
    ("sympla", "detalhe"): _sympla_detalhe,
    ("shotgun", "catalogo"): _shotgun_catalogo,
}


def _lotes_sympla(p):
    """Lotes do BFF de tickets: *.decimal já vem em R$ COM a taxa embutida
    (49,50 = 45,00 + 4,50); feeMonetary traz a taxa separada."""
    lotes = []
    for t in (p.get("tickets") or []):
        if not isinstance(t, dict) or t.get("show") is False:
            continue
        gratis = bool(t.get("isFree"))
        preco = 0.0 if gratis else None
        if not gratis:
            for chave in ("salePriceWithDiscountMonetary", "salePriceMonetary"):
                v = (t.get(chave) or {}).get("decimal")
                if isinstance(v, (int, float)):
                    preco = float(v)
                    break
        taxa = (t.get("feeMonetary") or {}).get("decimal")
        lotes.append({"nome": t.get("name"), "preco": preco,
                      "taxa": float(taxa) if isinstance(taxa, (int, float)) else None,
                      "gratis": gratis,
                      "esgotado": 1 if (t.get("currentAvailableQty") or 0) == 0
                      else 0})
    return lotes


def _lotes_ingresse(p):
    """Lotes do embed de checkout: responseData[] é o setor/passaporte, cada um
    com type[] de lotes. price vem SEM a taxa (tax separada) — normalizamos
    preco para o total a pagar."""
    lotes = []
    for item in (p.get("detail") or {}).get("responseData") or []:
        if not isinstance(item, dict):
            continue
        setor = (item.get("name") or "").strip()
        for tp in (item.get("type") or []):
            if not isinstance(tp, dict) or tp.get("hidden"):
                continue
            nome = (tp.get("name") or "").strip() or None
            if setor and nome and setor.casefold() != nome.casefold():
                nome = f"{setor} — {nome}"
            elif setor and not nome:
                nome = setor
            preco = tp.get("price")
            taxa = tp.get("tax")
            taxa = float(taxa) if isinstance(taxa, (int, float)) else None
            total = (float(preco) + (taxa or 0.0)
                     if isinstance(preco, (int, float)) else None)
            lotes.append({"nome": nome, "preco": total, "taxa": taxa,
                          "gratis": total == 0,
                          "esgotado": 1 if tp.get("status") == "finished"
                          else 0})
    return lotes


def _lotes_shotgun(p):
    """JSON-LD: offers[] com name/price (total; a fonte não separa taxa)."""
    offers = p.get("offers") or []
    offers = [o for o in (offers if isinstance(offers, list) else [offers])
              if isinstance(o, dict)]
    lotes = []
    for o in offers:
        preco = None
        for chave in ("lowPrice", "price"):
            try:
                preco = float(o[chave])
                break
            except (KeyError, TypeError, ValueError):
                continue
        lotes.append({"nome": o.get("name"), "preco": preco, "taxa": None,
                      "gratis": preco == 0,
                      "esgotado": 1 if str(o.get("availability", ""))
                      .endswith("SoldOut") else 0})
    return lotes


# (fonte, origem) -> função payload -> lista de lotes (dicts).
_LOTES = {
    ("sympla", "tickets"): _lotes_sympla,
    ("ingresse", "tickets"): _lotes_ingresse,
    ("shotgun", "catalogo"): _lotes_shotgun,
}


def _agregar(lotes):
    """Colunas de eventos que resumem os lotes. Leitura combinada:
    preco_min=38.99 + tem_gratis=1 -> "grátis em condições, pagos a partir de
    R$ 38,99"; preco_min NULL + tem_gratis=1 -> evento grátis."""
    pagos = [lt["preco"] for lt in lotes
             if not lt["gratis"] and lt["preco"] is not None]
    return {"preco_min": min(pagos) if pagos else None,
            "tem_gratis": 1 if any(lt["gratis"] and lt["esgotado"] != 1
                                   for lt in lotes) else 0,
            "esgotado": 1 if all(lt["esgotado"] == 1 for lt in lotes) else 0}


def aplicar(con):
    """Reseta e recalcula colunas derivadas e lotes a partir de eventos_raw.

    Retorna {coluna: quantos eventos ganharam valor} (+ chave "lotes" com o
    total de lotes gravados), para o relatório.
    """
    con.execute("UPDATE eventos SET " +
                ", ".join(f"{c} = NULL" for c in COLS_DERIVADAS))
    con.execute("DELETE FROM lotes")
    contagem = dict.fromkeys(COLS_DERIVADAS, 0)
    contagem["lotes"] = 0
    rows = con.execute(
        "SELECT r.evento_id, r.origem, r.payload, e.fonte "
        "FROM eventos_raw r JOIN eventos e ON e.id = r.evento_id").fetchall()
    for r in rows:
        derivacao = _DERIVACOES.get((r["fonte"], r["origem"]))
        extrator = _LOTES.get((r["fonte"], r["origem"]))
        if not derivacao and not extrator:
            continue
        payload = json.loads(r["payload"])
        campos = {}
        if derivacao:
            campos = {c: v for c, v in derivacao(payload).items()
                      if v is not None}
        if extrator:
            lotes = extrator(payload)
            if lotes:
                con.executemany(
                    "INSERT INTO lotes (evento_id, ordem, nome, preco, taxa, "
                    "gratis, esgotado) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(r["evento_id"], i, lt["nome"], lt["preco"], lt["taxa"],
                      1 if lt["gratis"] else 0, lt["esgotado"])
                     for i, lt in enumerate(lotes)])
                contagem["lotes"] += len(lotes)
                campos.update({c: v for c, v in _agregar(lotes).items()
                               if v is not None})
        if not campos:
            continue
        con.execute(
            "UPDATE eventos SET " + ", ".join(f"{c} = ?" for c in campos) +
            " WHERE id = ?", [*campos.values(), r["evento_id"]])
        for c in campos:
            contagem[c] += 1
    con.commit()
    return contagem
