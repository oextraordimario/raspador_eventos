"""Tratamento do ZIG (SuperTicket): payload de `cru.zig` → colunas de
`tratado.eventos` e `tratado.lotes`.

Este arquivo sabe LER o Zig; `coleta/zig.py` sabe FALAR com ele.

O preço do Zig NÃO vem do endpoint JSON de tickets (responde vazio) nem do
json_ld (preços errados): vem do `__NEXT_DATA__` da página pública — daí a era
'next-data' na origem 'tickets' (NI-23).
"""


def catalogo(p):
    bairro = ((p.get("event_location") or {}).get("neighborhood") or "").strip()
    return {"bairro": bairro or None}


def lotes(p):
    """`pageProps.tickets` da página pública: tickets[] com `value` (R$) e `fee`
    separada (~12%) — preco = total a pagar (value + fee), como no Ingresse.
    `unavailables[]` traz os esgotados na mesma forma. O nome já vem com setor e
    condição embutidos ("Geral [Adulto - Meia Entrada] Individual"); quando não
    vem, prefixamos o `sector_name`."""
    esgotados = {t.get("id") for t in (p.get("unavailables") or [])
                 if isinstance(t, dict)}
    saida, vistos = [], set()
    for t in (p.get("tickets") or []) + (p.get("unavailables") or []):
        if (not isinstance(t, dict) or t.get("public") == 0
                or t.get("id") in vistos):
            continue
        vistos.add(t.get("id"))
        valor = t.get("value")
        taxa = t.get("fee")
        taxa = float(taxa) if isinstance(taxa, (int, float)) else None
        preco = (round(float(valor) + (taxa or 0.0), 2)
                 if isinstance(valor, (int, float)) else None)
        nome = (t.get("name") or "").strip() or None
        setor = (t.get("sector_name") or "").strip()
        if setor and nome and not nome.casefold().startswith(setor.casefold()):
            nome = f"{setor} — {nome}"
        elif setor and not nome:
            nome = setor
        saida.append({"nome": nome, "preco": preco, "taxa": taxa,
                      "gratis": preco == 0,
                      "esgotado": 1 if t.get("id") in esgotados else 0})
    return saida


DERIVACOES = {"catalogo": catalogo}
LOTES = {"tickets": lotes}
