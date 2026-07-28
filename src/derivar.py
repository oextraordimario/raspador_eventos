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
  (zig, tickets), (ticketandgo, tickets) -> tabela lotes, com preco
  normalizado como TOTAL a pagar (Sympla já embute a taxa; Ingresse e Zig
  somam preço+taxa separada; Ticket and Go soma
  valor + valor×taxa_conveniencia). preco_min/esgotado/tem_gratis de eventos
  são AGREGAÇÕES dos lotes: preco_min = menor lote PAGO (cortesia não mascara
  mais o preço real), tem_gratis = há lote grátis não esgotado, esgotado =
  todos os lotes esgotados.

Derivações do mesmo evento nunca disputam coluna (cada origem preenche colunas
distintas), então a ordem de aplicação não importa.

Domínio cinema (spec 20260711_raspagem-cinema): aplicar_cinema() reconstrói
filmes/sessoes do zero a partir de cinema_raw — mesmo princípio, tabelas
próprias (sessão de cinema não vira evento).

Instagram (spec 20260723_instagram-como-fonte): aplicar_instagram() reconstrói
os eventos fonte='instagram' do zero a partir de instagram_raw (post +
extração do flyer) — a Prata do Instagram é a própria tabela eventos. Roda
DEPOIS de aplicar() (que trunca lotes e zera as colunas derivadas de todos).
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


def _lotes_zig(p):
    """pageProps.tickets da pagina publica (NI-23): tickets[] com value (R$)
    e fee separada (~12%) — preco = total a pagar (value + fee), como no
    Ingresse. unavailables[] traz os esgotados na mesma forma. O nome ja vem
    com setor e condicao embutidos ("Geral [Adulto - Meia Entrada]
    Individual") — quando nao vem, prefixamos o sector_name."""
    esgotados = {t.get("id") for t in (p.get("unavailables") or [])
                 if isinstance(t, dict)}
    lotes, vistos = [], set()
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
        lotes.append({"nome": nome, "preco": preco, "taxa": taxa,
                      "gratis": preco == 0,
                      "esgotado": 1 if t.get("id") in esgotados else 0})
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
    ("zig", "tickets"): _lotes_zig,
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
        "titulo_original": m.get("originalTitle") or None,
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

    con.execute("DELETE FROM tratado.sessoes")
    con.execute("DELETE FROM tratado.filmes")
    filmes, sessoes = {}, {}
    for r in con.execute("SELECT cinema_id, dia, payload, raspado_em "
                         "FROM cru.cinema ORDER BY dia").fetchall():
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
            f"INSERT INTO tratado.filmes ({','.join(cols)}) "
            f"VALUES ({','.join('%s' for _ in cols)})",
            [[f[c] for c in cols] for f in filmes.values()])
    if sessoes:
        cols = list(next(iter(sessoes.values())))
        con.cursor().executemany(
            f"INSERT INTO tratado.sessoes ({','.join(cols)}) "
            f"VALUES ({','.join('%s' for _ in cols)})",
            [[s[c] for c in cols] for s in sessoes.values()])
    # Enriquecimento externo (NI-36/NI-37): a Bronze cinema_extra_raw
    # sobrevive ao snapshot, então re-aplicar aqui é o que faz nota/sinopse/
    # pôster próprio voltarem depois de cada reconstrução. `escolhido` None =
    # o matching não confiou — não grava nada (auditoria fica no payload).
    tmdb_ok = 0
    for r in con.execute("SELECT filme_id, origem, payload "
                         "FROM cru.cinema_extra").fetchall():
        if r["filme_id"] not in filmes:
            continue  # filme fora de cartaz; a Bronze fica para reexibição
        extra = json.loads(r["payload"])
        if r["origem"] == "tmdb" and extra.get("escolhido"):
            e = extra["escolhido"]
            lanc = e.get("release_date") or ""
            con.execute(
                "UPDATE tratado.filmes SET sinopse = %s, ano = %s, nota = %s, "
                "votos = %s, tmdb_id = %s WHERE id = %s",
                (e.get("overview") or None,
                 int(lanc[:4]) if len(lanc) >= 4 else None,
                 # nota sem voto é ruído do TMDB, não avaliação
                 e.get("vote_average") if e.get("vote_count") else None,
                 e.get("vote_count") or None,
                 str(e["id"]) if e.get("id") is not None else None,
                 r["filme_id"]))
            tmdb_ok += 1
        elif r["origem"] == "poster" and extra.get("url"):
            con.execute("UPDATE tratado.filmes SET poster_proprio = %s WHERE id = %s",
                        (extra["url"], r["filme_id"]))
    con.commit()
    return {"filmes": len(filmes), "sessoes": len(sessoes), "tmdb": tmdb_ok}


def _itens_extracao(ext):
    """Itens de evento de uma extração, nos DOIS formatos: v1.1 é
    {"eventos": [...]} (0 = não-evento, 1 = post comum, N = carrossel-agenda);
    o formato antigo (objeto único com e_evento, pré-v1.1) vira lista de 0/1 —
    adaptador do backfill (spec §8.5): nada precisa re-extrair em massa."""
    if "eventos" in ext:
        return [i for i in (ext["eventos"] or []) if isinstance(i, dict)]
    return [ext] if ext.get("e_evento") is True else []


def _evento_instagram(perfil_info, code, post, item, n=None):
    """Um ITEM extraído (+ post) → dict de evento normalizado, ou None se a
    guarda reprova (só vira evento item com confiança ALTA, nome e data
    resolvida ≥ a data do post — errar para o lado de NÃO criar: falso evento
    é pior que evento perdido, a plataforma de ingresso cobre o grosso).

    n = posição 1-based do item quando o post tem VÁRIOS eventos (spec §8.3):
    id vira instagram:<code>:<n> e a URL ganha ?img_index=<n> (parâmetro real
    do Instagram — abre o carrossel perto da página certa e dá a URL única
    que o detalhar_evento exige). Post de item único mantém id/URL do v1.
    """
    from scrapers import instagram

    nome = (item.get("nome") or "").strip()
    if item.get("confianca") != "alta" or not nome:
        return None
    start = instagram.montar_start_date(item, post.get("taken_at"))
    if not start:
        return None
    legenda = (instagram.legenda_do_post(post) or "").strip()
    preco = item.get("preco")
    if not isinstance(preco, (int, float)) or isinstance(preco, bool):
        preco = None  # "true"/texto do LLM não é preço
    flyer = [f"{rotulo}: {valor}" for rotulo, valor in [
        ("Data", item.get("data")), ("Hora", item.get("hora")),
        ("Entrada", f"R$ {preco:.2f}".replace(".", ",")
         if preco is not None else None),
        ("Line-up", ", ".join(item["lineup"]) if item.get("lineup") else None),
        ("Local", item.get("local")), ("Obs", item.get("observacoes")),
    ] if valor]
    descricao = (legenda + ("\n\n[Do flyer] " + " · ".join(flyer)
                            if flyer else "")).strip() or None
    e_casa = perfil_info.get("tipo") != "produtora"
    sufixo = f":{n}" if n else ""
    return {
        "id": f"instagram:{code}{sufixo}",
        "fonte": "instagram",
        "id_nativo": f"{code}{sufixo}",
        "nome": nome,
        "start_date": start,
        "end_date": None,
        # cidade/estado rotulados (recorte da watchlist é Brasília — mesmo
        # precedente do Shotgun/Ticket and Go); a casa É o local, exceto em
        # perfil de produtora (aí o local vem do flyer, quando extraído).
        "cidade": "Brasília",
        "estado": "DF",
        "local_nome": (perfil_info["nome"] if e_casa
                       else (item.get("local") or None)),
        "endereco": None, "lat": None, "lon": None,
        "categoria": None,
        "organizador": perfil_info["nome"],
        "url": f"https://www.instagram.com/p/{code}/"
               + (f"?img_index={n}" if n else ""),
        # a URL do CDN da fonte expira em horas — NUNCA gravá-la. O que entra
        # aqui (via aplicar_instagram) é a cópia no storage próprio (NI-37).
        "imagem": None,
        "descricao": descricao,
        "atracoes": "; ".join(item["lineup"]) if item.get("lineup") else None,
        "preco_min": None,   # agregado do lote sintético, como nas outras fontes
        "_preco_flyer": preco,   # já saneado; vira o lote sintético (não é coluna)
    }


def aplicar_instagram(con):
    """Reconstrói os eventos fonte='instagram' do zero a partir de
    instagram_raw (post + extração). Idempotente e a seco: mudar a guarda ou
    o mapeamento é `--so-derivar`, sem re-raspar nem re-extrair.

    Roda DEPOIS de aplicar(): aquele trunca a tabela lotes inteira e zera as
    colunas derivadas; este reinsere o lote sintético do flyer e as agregações
    dos eventos do Instagram. `raspado_em` = o da raspagem do post — mas a
    fonte fica FORA do _marcar_sumidos (post sai da 1ª página do perfil sem
    significar cancelamento; evento do Instagram morre por data passada).

    Retorna {"eventos": n, "lotes": n, "descartados": n} para o relatório.
    """
    import store
    from scrapers import instagram

    perfis = {p["usuario"]: p for p in instagram.carregar_watchlist()}
    # flyer re-hospedado no storage próprio (origem='midia', NI-34/NI-37):
    # é a ÚNICA URL de imagem que pode ir para eventos.imagem
    midias = {r["code"]: json.loads(r["payload"]).get("url")
              for r in con.execute("SELECT code, payload FROM cru.instagram "
                                   "WHERE origem = 'midia'")}
    rows = con.execute(
        "SELECT p.perfil, p.code, p.payload AS post, p.raspado_em, "
        "       x.payload AS extracao "
        "FROM cru.instagram p JOIN cru.instagram x "
        "  ON x.code = p.code AND x.origem = 'extracao' "
        "WHERE p.origem = 'post' ORDER BY p.code").fetchall()
    eventos, lotes, descartados = [], [], 0
    for r in rows:
        post, ext = json.loads(r["post"]), json.loads(r["extracao"])
        # perfil que saiu da watchlist ainda deriva (o dado já foi pago);
        # fallback: o próprio @ como nome.
        info = perfis.get(r["perfil"], {"nome": r["perfil"], "tipo": "casa"})
        itens = _itens_extracao(ext)
        # n é a POSIÇÃO na lista extraída (estável: a extração roda 1x e fica
        # cacheada na Bronze), contando também itens reprovados pela guarda —
        # mudar a guarda não renumera os ids dos que sobrevivem.
        multi = len(itens) > 1
        do_post = 0
        for n, item in enumerate(itens, 1):
            ev = _evento_instagram(info, r["code"], post, item,
                                   n=n if multi else None)
            if not ev:
                continue
            ev["raspado_em"] = r["raspado_em"]
            ev["imagem"] = midias.get(r["code"])
            preco = ev.pop("_preco_flyer")
            eventos.append(ev)
            do_post += 1
            if preco is not None:
                lotes.append({"evento_id": ev["id"], "ordem": 0,
                              "nome": "entrada (do flyer)",
                              "preco": float(preco), "taxa": None,
                              "gratis": preco == 0, "esgotado": 0})
        if not do_post:
            descartados += 1
    con.execute("DELETE FROM tratado.lotes WHERE evento_id LIKE 'instagram:%'")
    con.execute("DELETE FROM tratado.eventos WHERE fonte = 'instagram'")
    if eventos:
        store.upsert_eventos(con, eventos)
    for lt in lotes:
        con.execute(
            "INSERT INTO tratado.lotes (evento_id, ordem, nome, preco, taxa, gratis, "
            "esgotado) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (lt["evento_id"], lt["ordem"], lt["nome"], lt["preco"], lt["taxa"],
             1 if lt["gratis"] else 0, lt["esgotado"]))
        agg = _agregar([lt])
        con.execute(
            "UPDATE tratado.eventos SET preco_min = %s, tem_gratis = %s, esgotado = %s"
            " WHERE id = %s", (agg["preco_min"], agg["tem_gratis"],
                               agg["esgotado"], lt["evento_id"]))
    con.commit()
    return {"eventos": len(eventos), "lotes": len(lotes),
            "descartados": descartados}


def aplicar(con):
    """Reseta e recalcula colunas derivadas e lotes a partir de eventos_raw.

    Retorna {coluna: quantos eventos ganharam valor} (+ chave "lotes" com o
    total de lotes gravados), para o relatório.
    """
    con.execute("UPDATE tratado.eventos SET " +
                ", ".join(f"{c} = NULL" for c in COLS_DERIVADAS))
    con.execute("DELETE FROM tratado.lotes")
    contagem = dict.fromkeys(COLS_DERIVADAS, 0)
    contagem["lotes"] = 0
    rows = con.execute(
        "SELECT r.evento_id, r.origem, r.payload, e.fonte "
        "FROM cru.eventos_raw r JOIN tratado.eventos e ON e.id = r.evento_id").fetchall()
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
                    "INSERT INTO tratado.lotes (evento_id, ordem, nome, preco, taxa, "
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
            "UPDATE tratado.eventos SET " + ", ".join(f"{c} = %s" for c in campos) +
            " WHERE id = %s", [*campos.values(), r["evento_id"]])
        for c in campos:
            contagem[c] += 1
    con.commit()
    return contagem
