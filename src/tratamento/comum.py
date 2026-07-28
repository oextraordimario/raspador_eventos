"""Escrita na camada TRATADO — o motor comum das trilhas de tratamento.

O que cada `tratamento/<fonte>.py` declara é só o MAPEAMENTO da sua fonte; o
upsert, as guardas e a agregação moram aqui, para o esqueleto não duplicar sete
vezes e as cópias divergirem por descuido.

⚠️ VIOLAÇÃO DE CAMADA CONHECIDA, e de propósito: hoje quem chama
`upsert_eventos` é a COLETA (pipeline/atualizar.py, logo depois de raspar), não
o tratamento. É exatamente o NI-55 — a prata é escrita pela coleta, e por isso
não se reconstrói do cru. A fatia 7 da spec 20260728_arquitetura-medalhao
inverte isso. Ter esta função em `tratamento/` enquanto `coleta/` a importa
deixa a violação VISÍVEL no grafo de imports, em vez de escondida.
"""

from base import tempo
from coleta import gravar

# Colunas de data normalizadas na escrita (invariante do schema: ISO UTC
# "+00:00", via tempo.norm_ts) — é o que torna a comparação lexical segura.
_COLS_DATA = {"start_date", "end_date", "raspado_em"}

# Campos ricos que podem ser colhidos num passo separado do catálogo (o
# "descrever"): no upsert, valor novo NULL preserva o que já está na base.
#
# `categoria` está aqui desde 2026-07-28: o "descrever" colhe a categoria real
# do Sympla e a raspagem seguinte do catálogo a sobrescrevia. Isto só funciona
# porque o catálogo passou a mandar categoria NULL (ver coleta/sympla.py) —
# COALESCE não protege contra valor novo NÃO-nulo, e o `event_type` do catálogo
# é 'NORMAL' em 100% dos eventos.
_COLS_PRESERVAR = {"descricao", "atracoes", "preco_min", "categoria"}


def upsert_eventos(con, eventos):
    """Insere ou atualiza uma lista de eventos normalizados (dicts).

    As colunas de data passam por tempo.norm_ts aqui — é o único ponto de
    escrita, então é ele que garante o invariante do schema (ISO UTC "+00:00",
    comparável lexicalmente).

    A chave reservada "_raw" (payload bruto que o normalizador da fonte
    recebeu) não é coluna de eventos: vai para cru.eventos_raw como origem
    'catalogo'. Dicts sem "_raw" seguem funcionando.
    """
    cols = ["id", "fonte", "id_nativo", "nome", "start_date", "end_date",
            "cidade", "estado", "local_nome", "endereco", "lat", "lon",
            "categoria", "organizador", "url", "imagem", "raspado_em",
            "descricao", "atracoes", "preco_min"]
    placeholders = ",".join("%s" for _ in cols)
    # O nome sem schema (`eventos.`) é como o Postgres expõe a tabela-alvo
    # dentro do ON CONFLICT DO UPDATE, mesmo com o INSERT qualificado.
    updates = ",".join(
        f"{c}=COALESCE(excluded.{c}, eventos.{c})" if c in _COLS_PRESERVAR
        else f"{c}=excluded.{c}"
        for c in cols if c != "id")
    sql = (f"INSERT INTO tratado.eventos ({','.join(cols)}) "
           f"VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    con.cursor().executemany(sql, [
        [tempo.norm_ts(e.get(c)) if c in _COLS_DATA else e.get(c) for c in cols]
        for e in eventos])
    for e in eventos:
        if e.get("_raw") is not None:
            gravar.gravar_raw(con, e["id"], "catalogo", e["_raw"],
                              e["raspado_em"], commit=False)
    con.commit()
    return len(eventos)
