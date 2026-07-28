"""Tratamento do SYMPLA: payload de `cru.sympla` → colunas de `tratado.eventos`
e linhas de `tratado.lotes`. A seco — nenhuma requisição de rede.

Este arquivo sabe LER o Sympla; `coleta/sympla.py` sabe FALAR com ele. Até
2026-07-28 esse conhecimento estava partido em três lugares que ninguém lembrava
que se relacionavam: o `_normalizar` do scraper, `derivar._sympla_*` e
`derivar._lotes_sympla`.

Campo novo do bruto = uma função aqui + `--so-derivar`, sem re-raspar.
"""


def catalogo(p):
    """Payload do discovery-bff → colunas derivadas."""
    bairro = ((p.get("location") or {}).get("neighborhood") or "").strip()
    score = p.get("global_score")
    return {"bairro": bairro or None,
            "popularidade": score if isinstance(score, (int, float)) else None}


def detalhe(p):
    """Payload do BFF de página → colunas derivadas.

    `categoria` vem daqui e SÓ daqui: o `event_type` do catálogo é 'NORMAL' em
    100% dos eventos (flag de modalidade, não categoria) e destruía este valor
    a cada rodada. Spec §6.2.
    """
    cat = p.get("eventsCategory")
    if isinstance(cat, dict):
        cat = cat.get("name")
    return {"cancelado": 1 if p.get("cancelled") else 0,
            "categoria": cat.strip() if isinstance(cat, str) and cat.strip()
            else None}


def lotes(p):
    """Lotes do BFF de tickets: *.decimal já vem em R$ COM a taxa embutida
    (49,50 = 45,00 + 4,50); feeMonetary traz a taxa separada."""
    saida = []
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
        saida.append({"nome": t.get("name"), "preco": preco,
                      "taxa": float(taxa) if isinstance(taxa, (int, float))
                      else None,
                      "gratis": gratis,
                      "esgotado": 1 if (t.get("currentAvailableQty") or 0) == 0
                      else 0})
    return saida


DERIVACOES = {"catalogo": catalogo, "detalhe": detalhe}
LOTES = {"tickets": lotes}
