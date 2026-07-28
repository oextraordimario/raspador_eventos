"""Tratamento do INGRESSE: payload de `cru.ingresse` → `tratado.lotes`.

Este arquivo sabe LER o Ingresse; `coleta/ingresse.py` sabe FALAR com ele.
O catálogo do Ingresse não traz nada derivável além do que já entra no upsert,
então só há extrator de lotes.
"""


def lotes(p):
    """Lotes do embed de checkout: responseData[] é o setor/passaporte, cada um
    com type[] de lotes. `price` vem SEM a taxa (`tax` separada) — normalizamos
    `preco` para o TOTAL a pagar, como nas outras fontes."""
    saida = []
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
            saida.append({"nome": nome, "preco": total, "taxa": taxa,
                          "gratis": total == 0,
                          "esgotado": 1 if tp.get("status") == "finished"
                          else 0})
    return saida


DERIVACOES = {}
LOTES = {"tickets": lotes}
