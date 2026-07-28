"""Tratamento do INSTAGRAM: `cru.instagram` (post + extração do flyer) →
eventos `fonte='instagram'` em `tratado.eventos`.

A "prata" do Instagram é a própria tabela de eventos: não há tabela
intermediária. Idempotente e a seco — mudar a guarda ou o mapeamento é
`--so-derivar`, sem re-raspar nem re-extrair (a extração por visão custa
dinheiro e roda uma vez por post).

Roda DEPOIS de comum.aplicar(), que trunca `tratado.lotes` inteira e zera as
colunas derivadas de todos; este reinsere o lote sintético do flyer e as
agregações dos eventos do Instagram.

A fonte fica FORA do `_marcar_sumidos`: post que sai da 1ª página do perfil não
significa cancelamento — evento do Instagram morre por data passada.
Spec: docs/specs/20260723_instagram-como-fonte/.
"""

import json

from tratamento import comum


def _itens_extracao(ext):
    """Itens de evento de uma extração, nos DOIS formatos: v1.1 é
    {"eventos": [...]} (0 = não-evento, 1 = post comum, N = carrossel-agenda);
    o formato antigo (objeto único com e_evento, pré-v1.1) vira lista de 0/1 —
    adaptador do backfill: nada precisa re-extrair em massa."""
    if "eventos" in ext:
        return [i for i in (ext["eventos"] or []) if isinstance(i, dict)]
    return [ext] if ext.get("e_evento") is True else []


def _evento(perfil_info, code, post, item, n=None):
    """Um ITEM extraído (+ post) → dict de evento normalizado, ou None se a
    guarda reprova.

    GUARDA POR ITEM: só vira evento item com confiança ALTA, nome e data
    resolvida. Errar para o lado de NÃO criar — falso evento é pior que evento
    perdido, porque a plataforma de ingresso cobre o grosso.

    n = posição 1-based do item quando o post tem VÁRIOS eventos: o id vira
    instagram:<code>:<n> e a URL ganha ?img_index=<n> (parâmetro real do
    Instagram — abre o carrossel perto da página certa e dá a URL única que o
    detalhar_evento exige). Post de item único mantém id/URL do v1.
    """
    from coleta import instagram

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
        # cidade/estado rotulados (o recorte da watchlist é Brasília — mesmo
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
        # aqui é a cópia no storage próprio (operacao.midias).
        "imagem": None,
        "descricao": descricao,
        "atracoes": "; ".join(item["lineup"]) if item.get("lineup") else None,
        "preco_min": None,   # agregado do lote sintético, como nas outras fontes
        "_preco_flyer": preco,   # já saneado; vira o lote sintético (não é coluna)
    }


def aplicar(con):
    """Reconstrói os eventos fonte='instagram' do zero a partir do cru.

    Retorna {"eventos": n, "lotes": n, "descartados": n} para o relatório.
    """
    from coleta import instagram

    perfis = {p["usuario"]: p for p in instagram.carregar_watchlist()}
    # flyer re-hospedado no storage próprio: é a ÚNICA URL de imagem que pode
    # ir para eventos.imagem (a do CDN da fonte expira em horas).
    midias = {r["chave"]: r["url"] for r in con.execute(
        "SELECT chave, url FROM operacao.midias WHERE tipo = 'flyer'")}
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
        # cacheada no cru), contando também itens reprovados pela guarda —
        # mudar a guarda não renumera os ids dos que sobrevivem.
        multi = len(itens) > 1
        do_post = 0
        for n, item in enumerate(itens, 1):
            ev = _evento(info, r["code"], post, item, n=n if multi else None)
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
        comum.upsert_eventos(con, eventos)
    for lt in lotes:
        con.execute(
            "INSERT INTO tratado.lotes (evento_id, ordem, nome, preco, taxa, "
            "gratis, esgotado) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (lt["evento_id"], lt["ordem"], lt["nome"], lt["preco"], lt["taxa"],
             1 if lt["gratis"] else 0, lt["esgotado"]))
        agg = comum.agregar([lt])
        con.execute(
            "UPDATE tratado.eventos SET preco_min = %s, tem_gratis = %s, "
            "esgotado = %s WHERE id = %s",
            (agg["preco_min"], agg["tem_gratis"], agg["esgotado"],
             lt["evento_id"]))
    con.commit()
    return {"eventos": len(eventos), "lotes": len(lotes),
            "descartados": descartados}
