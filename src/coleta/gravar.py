"""Escrita na camada CRU — o único lugar onde payload de fonte entra na base.

Pertence ao estágio de COLETA: quem chama é quem acabou de falar com a fonte.
A regra que o desenho inteiro serve é que a coleta **nunca escreve em
`tratado`** — ela escreve em `cru` (aqui) e em `operacao` (telemetria).

APPEND-ONLY nas cinco plataformas: cada coleta que traz payload diferente do
último acrescenta uma versão; nada é apagado no lugar. Instagram, cinema e TMDB
seguem "último vence" por decisão explícita — ver sql/cru/*.sql, cada um
documenta a política da sua tabela e o porquê.
"""

import hashlib
import json

# Allowlist: o nome da tabela entra em f-string, então NUNCA pode vir de fora.
FONTES = ("sympla", "ingresse", "zig", "shotgun", "ticketandgo")

# Colunas próprias de cada fonte — o que a COLETA conhece e o payload não diz.
# É por isso que a tabela é por fonte: sem elas, a reconstrução teria que
# deduzir por convenção ("o recorte é Brasília, então...").
_EXTRAS = {
    "shotgun": ("cidade_label", "estado_label"),
    "ticketandgo": ("slug", "cidade_label", "estado_label"),
}

# Era do endpoint por (fonte, origem). Fica aqui, e não espalhada nos
# coletores, para a troca de API ser UMA linha — e porque é a coleta que sabe
# qual endpoint chamou. Payload gravado antes deste registro fica com NULL, que
# é a informação honesta: "não sabemos". Spec §6.3.
ERAS = {
    ("sympla", "catalogo"): "discovery-bff",
    ("sympla", "detalhe"): "event-page-bff",
    ("sympla", "tickets"): "event-page-bff-tickets",
    ("ingresse", "catalogo"): "api-site-search",
    ("ingresse", "detalhe"): "api-site-events",
    ("ingresse", "tickets"): "api-site-tickets",
    ("zig", "catalogo"): "superticket-events",
    ("zig", "detalhe"): "superticket-events",
    ("zig", "tickets"): "next-data",          # o endpoint JSON de tickets vem vazio
    ("shotgun", "catalogo"): "json-ld",
    ("ticketandgo", "catalogo"): "v2-site-list",
    ("ticketandgo", "tickets"): "v1-evento",  # rota antiga + sufixo /evento
}


def hash_payload(payload):
    """sha256 da forma CANÔNICA do payload.

    A canonização (`sort_keys`) entra SÓ no hash — o payload gravado é o que a
    fonte mandou, fiel. Sem isso, uma fonte que reordena chaves geraria versão
    nova a cada rodada sem ter mudado nada.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()


def gravar(con, fonte, id_nativo, origem, payload, raspado_em, api=None,
           commit=True, **extras):
    """Acrescenta uma versão em cru.<fonte>, se o payload mudou.

    A comparação é com a ÚLTIMA versão, não com "existe alguma igual": um
    payload que vai de A para B e volta para A registra as três transições — o
    comportamento certo para um lote que esgotou e voltou a ter estoque.

    Devolve True se gravou versão nova, False se o payload era igual ao último.
    """
    if fonte not in FONTES:
        raise ValueError(f"fonte fora da allowlist: {fonte!r}")
    permitidas = _EXTRAS.get(fonte, ())
    if set(extras) - set(permitidas):
        raise ValueError(f"colunas desconhecidas para cru.{fonte}: "
                         f"{sorted(set(extras) - set(permitidas))}")

    h = hash_payload(payload)
    cols = ["id_nativo", "origem", "raspado_em", "hash", "payload", "api",
            *permitidas]
    vals = [id_nativo, origem, raspado_em, h,
            json.dumps(payload, ensure_ascii=False),
            api if api is not None else ERAS.get((fonte, origem)),
            *(extras.get(c) for c in permitidas)]
    # ON CONFLICT DO UPDATE, e não DO NOTHING: a PK inclui `raspado_em`, então
    # o conflito só acontece quando a MESMA chave é coletada duas vezes no
    # MESMO instante registrado, com conteúdo diferente. Aí o segundo payload é
    # a informação melhor (é mais recente no relógio de parede, mesmo com o
    # timestamp igual) — descartá-lo em silêncio esconderia uma coleta real.
    cur = con.execute(
        f"INSERT INTO cru.{fonte} ({','.join(cols)}) "
        f"SELECT {','.join('%s' for _ in cols)} "
        f"WHERE (SELECT hash FROM cru.{fonte} "
        f"       WHERE id_nativo = %s AND origem = %s "
        f"       ORDER BY raspado_em DESC LIMIT 1) IS DISTINCT FROM %s "
        f"ON CONFLICT (id_nativo, origem, raspado_em) DO UPDATE SET "
        f"  hash = excluded.hash, payload = excluded.payload, "
        f"  api = excluded.api"
        + "".join(f", {c} = excluded.{c}" for c in permitidas),
        [*vals, id_nativo, origem, h])
    if commit:
        con.commit()
    return cur.rowcount > 0


def gravar_instagram_raw(con, itens, raspado_em, commit=True):
    """Grava payloads do Instagram em cru.instagram (último vence).

    itens = [(perfil, code, origem, payload)] — origem 'post'/'story' vem da
    raspagem; 'extracao' é o JSON do flyer (1 por post, incremental). Ao
    contrário do cinema, NÃO há poda: a tabela acumula (post que sai da 1ª
    página do perfil continua aqui — é dele que o evento deriva).

    NÃO é append-only, e é decisão, não descuido: o post não muda depois de
    publicado e a extração é incremental por design, então último-vence já é
    imutável na prática. Spec: 20260723_instagram-como-fonte e §3.6.

    Post em COLABORAÇÃO entre dois perfis da watchlist chega no lote com o
    mesmo (code, origem) duas vezes — o Postgres rejeita ON CONFLICT repetido
    no mesmo comando, então o lote é deduplicado antes (o PRIMEIRO perfil do
    lote fica dono do post; o payload é o mesmo).
    """
    if itens:
        unicos = {}
        for perfil, code, origem, payload in itens:
            unicos.setdefault((code, origem), (perfil, code, origem, payload))
        con.cursor().executemany(
            "INSERT INTO cru.instagram (perfil, code, origem, payload, "
            "raspado_em) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT(code, origem) DO UPDATE SET "
            "payload = excluded.payload, raspado_em = excluded.raspado_em",
            [(perfil, code, origem, json.dumps(payload, ensure_ascii=False),
              raspado_em)
             for perfil, code, origem, payload in unicos.values()])
    if commit:
        con.commit()
    return len(itens)


def gravar_cinema_raw(con, itens, raspado_em):
    """Grava a grade bruta do cinema em cru.cinema (último vence) e poda os
    dias que já ficaram no passado — o snapshot da grade corrente é o único com
    valor de consulta, e histórico custaria 20 KB × 64 por rodada para
    responder pergunta que ninguém faz. Cinema×dia ausente de `itens` (falha de
    rede) mantém o payload anterior: buraco não apaga grade boa.
    Spec: 20260711_raspagem-cinema e §3.6.
    """
    if itens:
        con.cursor().executemany(
            "INSERT INTO cru.cinema (cinema_id, dia, payload, raspado_em) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT(cinema_id, dia) DO UPDATE SET "
            "payload = excluded.payload, raspado_em = excluded.raspado_em",
            [(cid, dia, json.dumps(payload, ensure_ascii=False), raspado_em)
             for cid, dia, payload in itens])
        con.execute("DELETE FROM cru.cinema WHERE dia < %s",
                    (min(dia for _, dia, _ in itens),))
    con.commit()
    return len(itens)


def gravar_tmdb(con, filme_id, payload, raspado_em):
    """Enriquecimento externo de UM filme em cru.tmdb. Incremental (só se busca
    filme sem linha) e último-vence: re-tentativa de um match que falhou deve
    sobrescrever, não acumular versão."""
    con.execute(
        "INSERT INTO cru.tmdb (filme_id, payload, raspado_em) "
        "VALUES (%s, %s, %s) "
        "ON CONFLICT(filme_id) DO UPDATE SET "
        "payload = excluded.payload, raspado_em = excluded.raspado_em",
        (filme_id, json.dumps(payload, ensure_ascii=False), raspado_em))
    con.commit()


def gravar_midia(con, chave, tipo, url, subido_em):
    """Registra uma mídia no NOSSO storage (operacao.midias): 'poster' de filme
    ou 'flyer' do Instagram. Não é payload de fonte — é artefato nosso, e por
    isso não mora no `cru`."""
    con.execute(
        "INSERT INTO operacao.midias (chave, tipo, url, subido_em) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(chave, tipo) DO UPDATE SET "
        "url = excluded.url, subido_em = excluded.subido_em",
        (chave, tipo, url, subido_em))
    con.commit()


def podar_historico(con, dias):
    """Poda o histórico do `cru`: passados `dias`, sobra só a última versão de
    cada (id_nativo, origem). É a ÚNICA exceção ao "nada é apagado", e nunca
    toca o estado atual — a versão mais recente de cada chave não tem sibling
    mais nova, então a condição do EXISTS nunca casa com ela.

    Sem poda, o append-only cresce ~2,7 MB/rodada (≈1 GB/ano): o `global_score`
    do Sympla muda todo dia e o `currentAvailableQty` dos tickets muda a cada
    ingresso vendido. Spec §3.5.
    """
    from datetime import datetime, timedelta, timezone
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    total = {}
    for fonte in FONTES:   # allowlist — nunca nome vindo de fora
        cur = con.execute(
            f"DELETE FROM cru.{fonte} a WHERE a.raspado_em < %s "
            f"  AND EXISTS (SELECT 1 FROM cru.{fonte} b "
            f"              WHERE b.id_nativo = a.id_nativo "
            f"                AND b.origem = a.origem "
            f"                AND b.raspado_em > a.raspado_em)", (corte,))
        if cur.rowcount:
            total[fonte] = cur.rowcount
    con.commit()
    return total
