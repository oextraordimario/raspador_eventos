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
  (zig, catalogo)     -> bairro (event_location.neighborhood)

Lotes de ingresso (specs 20260710_lotes-ingressos e 20260712_fontes-zig-
ticketandgo):
  (sympla, tickets), (ingresse, tickets), (shotgun, catalogo),
  (ticketandgo, tickets) -> tabela lotes, com preco normalizado como TOTAL a
  pagar (Sympla já embute a taxa; Ingresse soma price+tax; Ticket and Go soma
  valor + valor×taxa_conveniencia). preco_min/esgotado/tem_gratis de eventos
  são AGREGAÇÕES dos lotes: preco_min = menor lote PAGO (cortesia não mascara
  mais o preço real), tem_gratis = há lote grátis não esgotado, esgotado =
  todos os lotes esgotados.

Derivações do mesmo evento nunca disputam coluna (cada origem preenche colunas
distintas), então a ordem de aplicação não importa.

Domínio cinema (spec 20260711_raspagem-cinema): aplicar_cinema() reconstrói
filmes/sessoes do zero a partir de cinema_raw — mesmo princípio, tabelas
próprias (sessão de cinema não vira evento).
"""

import json

import tempo

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


def _zig_catalogo(p):
    bairro = ((p.get("event_location") or {}).get("neighborhood") or "").strip()
    return {"bairro": bairro or None}


# (fonte, origem) -> função payload -> {coluna: valor}; valor None é ignorado
# (não sobrescreve o que outra derivação tiver preenchido).
_DERIVACOES = {
    ("sympla", "catalogo"): _sympla_catalogo,
    ("sympla", "detalhe"): _sympla_detalhe,
    ("shotgun", "catalogo"): _shotgun_catalogo,
    ("zig", "catalogo"): _zig_catalogo,
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


def _lotes_ticketandgo(p):
    """Detalhe do evento: os lotes vêm em bilhetes[] (evento simples) OU
    aninhados em setores[].bilhetes[] (evento com setor — nome vira
    "setor — lote", como no Ingresse). taxa_conveniencia é FRAÇÃO sobre o
    valor (0.1 = 10%) — normalizamos preco para o total a pagar (valor +
    taxa). A fonte só lista lote à venda (sem flag de esgotado no payload) —
    esgotado fica 0."""
    try:
        fracao = float(p.get("taxa_conveniencia"))
    except (TypeError, ValueError):
        fracao = None
    grupos = [("", p.get("bilhetes") or [])]
    grupos += [((s.get("nome") or "").strip(), s.get("bilhetes") or [])
               for s in (p.get("setores") or []) if isinstance(s, dict)]
    lotes = []
    for setor, bilhetes in grupos:
        for b in bilhetes:
            if not isinstance(b, dict):
                continue
            try:
                valor = float(b.get("valor_bilhete") or b.get("valor"))
            except (TypeError, ValueError):
                valor = None
            taxa = round(valor * fracao, 2) if (valor and fracao) else None
            preco = valor + (taxa or 0.0) if valor is not None else None
            nome = (b.get("nome") or "").strip() or None
            if setor and nome and setor.casefold() != nome.casefold():
                nome = f"{setor} — {nome}"
            elif setor and not nome:
                nome = setor
            lotes.append({"nome": nome, "preco": preco, "taxa": taxa,
                          "gratis": preco == 0, "esgotado": 0})
    return lotes


# (fonte, origem) -> função payload -> lista de lotes (dicts).
_LOTES = {
    ("sympla", "tickets"): _lotes_sympla,
    ("ingresse", "tickets"): _lotes_ingresse,
    ("shotgun", "catalogo"): _lotes_shotgun,
    ("ticketandgo", "tickets"): _lotes_ticketandgo,
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


def _filme(m, raspado_em):
    """Payload de filme da Ingresso.com -> linha de filmes (a chave é o id
    estável do catálogo deles; sessionId, ao contrário, muda entre semanas)."""
    poster = next((i.get("url") for i in (m.get("images") or [])
                   if i.get("type") == "PosterPortrait"), None)
    trailer = next((t.get("url") for t in (m.get("trailers") or [])
                    if t.get("url")), None)
    try:
        duracao = int(m.get("duration"))
    except (TypeError, ValueError):
        duracao = None
    return {
        "id": str(m.get("id")),
        "titulo": m.get("title"),
        "generos": ", ".join(m.get("genres") or []) or None,
        "duracao_min": duracao,
        "classificacao": m.get("contentRating") or None,
        "distribuidora": m.get("distributor") or None,
        "url": m.get("siteURL") or None,
        "poster": poster,
        "trailer": trailer,
        "em_pre_venda": 1 if m.get("inPreSale") else 0,
        "raspado_em": raspado_em,
    }


def _sessoes_do_filme(m, cinema_id, apelido):
    """Sessões de um filme num cinema: uma linha por sessão, com os tipos
    exibíveis crus ("3D/XD/Dublado", "Cine Inclusivo/Dublado") — a condição
    é para o agente ler, não para regex (mesma regra dos lotes NI-18)."""
    for sala in (m.get("rooms") or []):
        for s in (sala.get("sessions") or []):
            inicio = tempo.norm_ts((s.get("date") or {}).get("localDate"))
            if not s.get("id") or not inicio:
                continue
            tipos = "/".join(t["name"] for t in (s.get("types") or [])
                             if t.get("display") and t.get("name")) or "2D"
            preco = s.get("price")
            yield {
                "id": str(s["id"]),
                "cinema": apelido,
                "cinema_id": cinema_id,
                "inicio": inicio,
                "sala": s.get("room") or sala.get("name"),
                "tipos": tipos,
                "preco": float(preco) if isinstance(preco, (int, float)) else None,
                "url_compra": s.get("siteURL") or None,
            }


def aplicar_cinema(con):
    """Reconstrói filmes e sessoes do zero a partir de cinema_raw (snapshot:
    a grade corrente substitui a anterior — sessão que saiu da grade não é
    reinserida; não há dedupe nem sumido no domínio cinema).

    Retorna {"filmes": n, "sessoes": n} para o relatório.
    """
    from scrapers.cinema import CINEMAS  # dict puro (apelido por theaterId)

    con.execute("DELETE FROM sessoes")
    con.execute("DELETE FROM filmes")
    filmes, sessoes = {}, {}
    for r in con.execute("SELECT cinema_id, dia, payload, raspado_em "
                         "FROM cinema_raw ORDER BY dia").fetchall():
        apelido = CINEMAS.get(r["cinema_id"], r["cinema_id"])
        for bloco in json.loads(r["payload"]):
            for m in (bloco.get("movies") or []):
                f = _filme(m, r["raspado_em"])
                if f["id"] and f["titulo"]:
                    filmes[f["id"]] = f  # último dia vence (dados iguais)
                for s in _sessoes_do_filme(m, r["cinema_id"], apelido):
                    s["filme_id"] = f["id"]
                    sessoes[s["id"]] = s
    if filmes:
        cols = list(next(iter(filmes.values())))
        con.cursor().executemany(
            f"INSERT INTO filmes ({','.join(cols)}) "
            f"VALUES ({','.join('%s' for _ in cols)})",
            [[f[c] for c in cols] for f in filmes.values()])
    if sessoes:
        cols = list(next(iter(sessoes.values())))
        con.cursor().executemany(
            f"INSERT INTO sessoes ({','.join(cols)}) "
            f"VALUES ({','.join('%s' for _ in cols)})",
            [[s[c] for c in cols] for s in sessoes.values()])
    con.commit()
    return {"filmes": len(filmes), "sessoes": len(sessoes)}


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
                con.cursor().executemany(
                    "INSERT INTO lotes (evento_id, ordem, nome, preco, taxa, "
                    "gratis, esgotado) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [(r["evento_id"], i, lt["nome"], lt["preco"], lt["taxa"],
                      1 if lt["gratis"] else 0, lt["esgotado"])
                     for i, lt in enumerate(lotes)])
                contagem["lotes"] += len(lotes)
                campos.update({c: v for c, v in _agregar(lotes).items()
                               if v is not None})
        if not campos:
            continue
        con.execute(
            "UPDATE eventos SET " + ", ".join(f"{c} = %s" for c in campos) +
            " WHERE id = %s", [*campos.values(), r["evento_id"]])
        for c in campos:
            contagem[c] += 1
    con.commit()
    return contagem
