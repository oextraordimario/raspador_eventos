"""Tratamento do INGRESSE: payload de `cru.ingresse` → `tratado.eventos` e
`tratado.lotes`.

Este arquivo sabe LER o Ingresse; `coleta/ingresse.py` sabe FALAR com ele.
"""

from base import texto


def normalizar(p, cru):
    """Payload da busca → as colunas de IDENTIDADE do evento (era
    `coleta/ingresse._normalizar`). None = payload não reconhecido (§6.3)."""
    if str(p.get("id") or "") != cru["id_nativo"]:
        return None
    place = p.get("place") or {}
    geo = place.get("location") or {}
    poster = p.get("poster") or p.get("images") or {}
    session = p.get("session") or {}
    return {
        "nome": p.get("title"),
        "start_date": session.get("dateTime") or p.get("event_date"),
        "end_date": None,  # a busca não retorna término
        "cidade": place.get("city") or None,
        "estado": place.get("state") or None,
        "local_nome": place.get("name") or None,
        "endereco": place.get("street") or None,
        "lat": geo.get("lat") or None,
        "lon": geo.get("lon") or None,
        "organizador": None,  # não vem no resultado de busca
        "url": (f"https://www.ingresse.com/{p['slug']}" if p.get("slug")
                else None),
        "imagem": poster.get("large") or poster.get("medium") or None,
    }


def detalhe(p):
    """Payload de /events/{slug} → a descrição. Antes o passo "descrever"
    escrevia direto em `tratado` (§6.1); hoje ele só grava no cru."""
    return {"descricao": texto.limpar_html(p.get("description"))}


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


DERIVACOES = {"detalhe": detalhe}
LOTES = {"tickets": lotes}
CONFERIR = {}
