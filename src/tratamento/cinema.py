"""Tratamento do CINEMA: `cru.cinema` (+ `cru.tmdb`, `operacao.midias`) →
`tratado.filmes` e `tratado.sessoes`.

SNAPSHOT, não upsert: o `sessionId` da Ingresso.com só é estável dentro da grade
corrente, então não há dedupe nem coluna `sumido` neste domínio — a grade nova
substitui a anterior inteira. O id do FILME, ao contrário, é estável entre
semanas, e por isso é a PK de `tratado.filmes`.

Sessão de cinema não vira evento: domínio próprio, tabelas próprias.
Spec: docs/specs/20260711_raspagem-cinema/.
"""

import json

from base import tempo


def _filme(m, raspado_em):
    """Payload de filme da Ingresso.com → linha de tratado.filmes."""
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
    exibíveis CRUS ("3D/XD/Dublado", "Cine Inclusivo/Dublado") — a condição é
    para o agente ler, não para regex (mesma regra dos lotes, NI-18)."""
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
                "preco": float(preco) if isinstance(preco, (int, float))
                else None,
                "url_compra": s.get("siteURL") or None,
            }


def aplicar(con):
    """Reconstrói filmes e sessoes do zero a partir de cru.cinema.

    Retorna {"filmes": n, "sessoes": n, "tmdb": n} para o relatório.
    """
    from coleta.cinema import CINEMAS  # dict puro (apelido por theaterId)

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

    # Enriquecimento externo (NI-36/NI-37): cru.tmdb e operacao.midias
    # sobrevivem ao snapshot, então re-aplicar aqui é o que faz nota/sinopse/
    # pôster próprio voltarem depois de cada reconstrução. `escolhido` None =
    # o matching não confiou — não grava nada (a auditoria fica no payload).
    tmdb_ok = 0
    for r in con.execute("SELECT filme_id, payload FROM cru.tmdb").fetchall():
        if r["filme_id"] not in filmes:
            continue  # filme fora de cartaz; o cru fica para quando reexibir
        e = (json.loads(r["payload"]) or {}).get("escolhido")
        if not e:
            continue
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
    for r in con.execute("SELECT chave, url FROM operacao.midias "
                         "WHERE tipo = 'poster'").fetchall():
        if r["chave"] in filmes:
            con.execute("UPDATE tratado.filmes SET poster_proprio = %s "
                        "WHERE id = %s", (r["url"], r["chave"]))
    # Sem commit: o ciclo inteiro do tratamento roda numa transação só
    # (tratamento/ciclo.py) — ver o cabeçalho de lá.
    return {"filmes": len(filmes), "sessoes": len(sessoes), "tmdb": tmdb_ok}
