"""Tratamento do SYMPLA: payload de `cru.sympla` → colunas de `tratado.eventos`
e linhas de `tratado.lotes`. A seco — nenhuma requisição de rede.

Este arquivo sabe LER o Sympla; `coleta/sympla.py` sabe FALAR com ele. Até
2026-07-28 esse conhecimento estava partido em três lugares que ninguém lembrava
que se relacionavam: o `_normalizar` do scraper, `derivar._sympla_*` e
`derivar._lotes_sympla`.

Campo novo do bruto = uma função aqui + `--so-derivar`, sem re-raspar.
"""

from base import texto


def normalizar(p, cru):
    """Payload do catálogo → as colunas de IDENTIDADE do evento.

    Era `coleta/sympla._normalizar`. Mudou de lado na fatia 7: quem lê o
    payload é o tratamento, sempre — inclusive para produzir nome, data e URL.

    Devolve None se o payload não for reconhecível como este evento (guarda
    genérica da §6.3: o id do payload TEM que bater com a chave da bronze,
    senão uma troca de API entrega campos homônimos de outro schema e a
    normalização degrada em silêncio).
    """
    if str(p.get("id") or "") != cru["id_nativo"]:
        return None
    loc = p.get("location") or {}
    org = p.get("organizer") or {}
    imgs = p.get("images") or {}
    return {
        "nome": p.get("name"),
        "start_date": p.get("start_date"),
        "end_date": p.get("end_date"),
        "cidade": loc.get("city") or None,
        "estado": loc.get("state") or None,
        "local_nome": loc.get("name") or None,
        "endereco": loc.get("address") or None,
        "lat": loc.get("lat") or None,
        "lon": loc.get("lon") or None,
        "organizador": org.get("name") or None,
        "url": p.get("url"),
        "imagem": imgs.get("lg") or imgs.get("original") or None,
    }


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

    `descricao` também: o passo "descrever" escrevia direto em `tratado` e por
    isso a prata não se reconstruía (§6.1). Hoje ele só grava o payload no cru,
    e a descrição sai daqui.
    """
    cat = p.get("eventsCategory")
    if isinstance(cat, dict):
        cat = cat.get("name")
    return {"cancelado": 1 if p.get("cancelled") else 0,
            "descricao": (texto.limpar_html(p.get("detail"))
                          or texto.limpar_html(p.get("strippedDetail"))),
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

# Guarda por origem (§6.3), VAZIA aqui — e a ausência é a decisão.
#
# A guarda do NI-17 (o BFF devolve um evento alheio, de outro namespace, sem
# erro HTTP) compara o nome que o BFF respondeu com o nome que já se tinha, e
# ela roda na COLETA, antes de o payload entrar no cru — é lá que os dois nomes
# são contemporâneos.
#
# Repeti-la na LEITURA foi testado contra a base real em 2026-07-28 e reprovado:
# o catálogo se move. O produtor do sympla:3512216 renomeou o evento ("Sábado
# Despedida do Brazólia..." → "Gelada, Pagode e Sentimento...") entre a coleta
# do detalhe e a última do catálogo; o id é o mesmo, o evento é o mesmo, e a
# guarda na leitura descartaria a descrição boa. Conferir por id não substitui:
# o BFF é consultado PELO id da URL, então ele sempre devolve esse id de volta
# — a checagem seria tautológica. O nome é o único sinal, e só vale fresco.
CONFERIR = {}
