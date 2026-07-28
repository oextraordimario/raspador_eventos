"""Escrita na camada CRU — o único lugar onde payload de fonte entra na base.

Pertence ao estágio de COLETA: quem chama é quem acabou de falar com a fonte.
A regra que o desenho inteiro serve é que a coleta **nunca escreve em
`tratado`** — ela escreve em `cru` (aqui) e em `operacao` (telemetria).

Hoje a política é "último payload vence" (UPSERT na PK). A fatia 5 da spec
20260728_arquitetura-medalhao troca isto por append-only com dedupe por hash,
uma tabela por fonte.
"""

import json


def gravar_raw(con, evento_id, origem, payload, raspado_em, commit=True):
    """Guarda o payload bruto de um evento na camada cru (último vence)."""
    con.execute(
        "INSERT INTO cru.eventos_raw (evento_id, origem, payload, raspado_em) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(evento_id, origem) DO UPDATE SET "
        "payload = excluded.payload, raspado_em = excluded.raspado_em",
        (evento_id, origem, json.dumps(payload, ensure_ascii=False), raspado_em))
    if commit:
        con.commit()


def gravar_instagram_raw(con, itens, raspado_em, commit=True):
    """Grava payloads do Instagram em cru.instagram (último vence).

    itens = [(perfil, code, origem, payload)] — origem 'post'/'story' vem da
    raspagem; 'extracao' é o JSON do flyer (1 por post, incremental); 'midia' é
    a URL da cópia no storage próprio. Ao contrário do cinema, NÃO há poda: a
    tabela acumula (post que sai da 1ª página do perfil continua aqui — é dele
    que o evento deriva). Spec: 20260723_instagram-como-fonte.

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
    valor de consulta. Cinema×dia ausente de `itens` (falha de rede na
    raspagem) mantém o payload anterior. Spec: 20260711_raspagem-cinema.
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


def gravar_cinema_extra(con, filme_id, origem, payload, raspado_em):
    """Grava um enriquecimento de filme na bronze ACUMULATIVA
    (cru.cinema_extra): match TMDB, cópia de pôster etc. Fora do snapshot de
    propósito — sobrevive à reconstrução de filmes/sessoes. Último vence
    (re-tentativa de match sobrescreve o anterior)."""
    con.execute(
        "INSERT INTO cru.cinema_extra (filme_id, origem, payload, raspado_em) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(filme_id, origem) DO UPDATE SET "
        "payload = excluded.payload, raspado_em = excluded.raspado_em",
        (filme_id, origem, json.dumps(payload, ensure_ascii=False), raspado_em))
    con.commit()
