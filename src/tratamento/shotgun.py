"""Tratamento do SHOTGUN: JSON-LD de `cru.shotgun` → colunas de
`tratado.eventos` e `tratado.lotes`.

Este arquivo sabe LER o Shotgun; `coleta/shotgun.py` sabe FALAR com ele — e é
só esse que conhece Playwright. Com o import do navegador no topo do módulo
antigo, ler um JSON-LD já gravado exigia a dependência inteira (spec §6.6).

O Shotgun tem uma origem só: o JSON-LD do catálogo já traz descrição, atrações,
organizador e preços, então ele não passa por descrever/precificar.
"""


def _atracoes(ld):
    """Line-up do JSON-LD (performer: dict ou lista de dicts) como texto '; '."""
    perf = ld.get("performer")
    if not perf:
        return None
    nomes = [p.get("name") for p in (perf if isinstance(perf, list) else [perf])
             if isinstance(p, dict) and p.get("name")]
    return "; ".join(nomes) or None


def normalizar(p, cru):
    """JSON-LD → as colunas de IDENTIDADE do evento (era
    `coleta/shotgun._normalizar`).

    Sem checagem de id: a chave da bronze é o SLUG da URL, que não existe
    dentro do JSON-LD. O que substitui a checagem é a guarda comum (nome e URL
    não-nulos) — e a URL sai do próprio slug, então nunca aponta para outro
    evento.

    `cidade`/`estado` vêm das colunas próprias de `cru.shotgun`, não do
    payload: o `addressLocality` do JSON-LD é o bairro *quando* não é a própria
    cidade (ver abaixo), e a cidade é o parâmetro de busca que a coleta usou.
    Gravar o que a coleta CONHECE é o que torna esta reconstrução possível sem
    adivinhar por convenção.
    """
    loc = p.get("location") or {}
    addr = loc.get("address") or {}
    org = p.get("organizer") or {}
    slug = cru["id_nativo"]

    # `addressLocality` é o campo de bairro do JSON-LD, mas a fonte o preenche
    # com a CIDADE em metade dos casos (38 de 70 dizem "Brasília", medido em
    # 2026-07-28; o resto diz "Asa Sul", "Saan"). Cidade não é bairro: deixar
    # passar encheria a faceta de bairro com uma opção que casa tudo.
    localidade = (addr.get("addressLocality") or "").strip() or None
    cidade = cru.get("cidade_label")
    bairro = None if not localidade or localidade == cidade else localidade
    return {
        "nome": p.get("name"),
        "start_date": p.get("startDate"),
        "end_date": p.get("endDate"),
        "cidade": cru.get("cidade_label"),
        "estado": cru.get("estado_label"),
        "local_nome": loc.get("name") or localidade,
        # o `streetAddress` é o endereço COMPLETO ("SBS Q. 1 - Asa Sul,
        # Brasília - DF, 70070-110") e existe em 68 dos 70 payloads. Ele vinha
        # sendo descartado porque a localidade tinha precedência — e a
        # localidade quase sempre é só "Brasília". Invertida a ordem, esta
        # fonte passa a ter endereço de verdade, que é também a matéria-prima
        # do dicionário de bairros (§5.2.2 da spec do rework).
        "endereco": addr.get("streetAddress") or localidade or None,
        "bairro": bairro,
        "lat": (loc.get("geo") or {}).get("latitude") or None,
        "lon": (loc.get("geo") or {}).get("longitude") or None,
        # `categoria` fica NULA de propósito. O normalizador antigo gravava a
        # constante "MusicEvent" — que é o @type do JSON-LD em 65 dos 65
        # eventos coletados (medido em 2026-07-28). É o MESMO antipadrão do
        # `event_type`='NORMAL' do Sympla que a §6.2 desmontou: rótulo com zero
        # poder de distinção, que só polui o FTS (indexa `categoria`).
        "categoria": None,
        "organizador": (org.get("name") if isinstance(org, dict) else None)
                       or None,
        "url": p.get("url") or f"https://shotgun.live/en/events/{slug}",
        "imagem": p.get("image") if isinstance(p.get("image"), str) else None,
        # campos ricos que o JSON-LD já entrega de graça — por isso o Shotgun
        # não passa pelos passos "descrever" e "precificar"
        "descricao": (p.get("description") or "").strip() or None,
        "atracoes": _atracoes(p),
    }


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
CONFERIR = {}
