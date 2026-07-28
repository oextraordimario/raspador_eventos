"""Tratamento do ZIG (SuperTicket): payload de `cru.zig` → colunas de
`tratado.eventos` e `tratado.lotes`.

Este arquivo sabe LER o Zig; `coleta/zig.py` sabe FALAR com ele.

O preço do Zig NÃO vem do endpoint JSON de tickets (responde vazio) nem do
json_ld (preços errados): vem do `__NEXT_DATA__` da página pública — daí a era
'next-data' na origem 'tickets' (NI-23).
"""

from base import texto


def normalizar(p, cru):
    """Payload do catálogo → as colunas de IDENTIDADE do evento (era
    `coleta/zig._normalizar`). None = payload não reconhecido (§6.3)."""
    if str(p.get("id") or "") != cru["id_nativo"]:
        return None
    loc = p.get("event_location") or {}
    slug = p.get("slug")
    return {
        "nome": p.get("name"),
        "start_date": p.get("start_date"),
        "end_date": p.get("end_date"),
        # a API manda " Brasília" com espaço na frente às vezes — trim
        "cidade": (loc.get("city") or "").strip() or None,
        "estado": (loc.get("state") or "").strip() or None,
        "local_nome": (loc.get("name") or "").strip() or None,
        "endereco": loc.get("formatted_address") or None,
        "lat": loc.get("lat") or None,
        "lon": loc.get("lng") or None,
        "organizador": None,  # só no detalhe (producer); não vale a requisição
        "url": f"https://zig.tickets/eventos/{slug}" if slug else None,
        "imagem": p.get("banner") or p.get("thumb")
                  or p.get("vertical_banner") or None,
    }


def catalogo(p):
    bairro = ((p.get("event_location") or {}).get("neighborhood") or "").strip()
    return {"bairro": bairro or None}


def detalhe(p):
    """Payload de /events/{slug} → a descrição. Muitos eventos do Zig têm
    `description` vazia tipo "<p><br></p>" — limpar_html devolve None."""
    return {"descricao": texto.limpar_html(p.get("description"))}


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


DERIVACOES = {"catalogo": catalogo, "detalhe": detalhe}
LOTES = {"tickets": lotes}

# Vazia pelo mesmo motivo do Sympla: a guarda de nome vale na COLETA, onde os
# dois nomes são contemporâneos. Na leitura ela vira falso positivo toda vez
# que a fonte renomeia um evento. Ver o comentário em tratamento/sympla.py.
CONFERIR = {}
