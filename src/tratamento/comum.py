"""O motor comum das trilhas de tratamento — escrita na camada TRATADO.

Cada `tratamento/<fonte>.py` declara só o MAPEAMENTO da sua fonte (dois dicts:
`DERIVACOES` e `LOTES`); o upsert, a agregação e o laço que percorre o `cru`
moram aqui. Sem isso o esqueleto duplicaria cinco vezes e as cópias divergiriam
por descuido — que é o risco real de separar por fonte.

⚠️ VIOLAÇÃO DE CAMADA CONHECIDA, e de propósito: hoje quem chama
`upsert_eventos` é a COLETA (pipeline/atualizar.py, logo depois de raspar), não
o tratamento. É exatamente o NI-55 — a prata é escrita pela coleta, e por isso
não se reconstrói do cru. A fatia 7 da spec 20260728_arquitetura-medalhao
inverte isso. Ter esta função em `tratamento/` enquanto `coleta/` a importa
deixa a violação VISÍVEL no grafo de imports, em vez de escondida.
"""

import json

from base import tempo
from coleta import gravar
from tratamento import ingresse, shotgun, sympla, ticketandgo, zig

# fonte -> módulo de tratamento. Uma trilha por fonte (spec D6):
#   coleta/<fonte>.py -> cru.<fonte> -> tratamento/<fonte>.py -> tratado.eventos
TRILHAS = {"sympla": sympla, "ingresse": ingresse, "zig": zig,
           "shotgun": shotgun, "ticketandgo": ticketandgo}

# Colunas de tratado.eventos preenchidas pela derivação (resetadas a cada
# aplicar() e recalculadas do zero a partir do cru — é isso que torna a prata
# reconstruível). `categoria` entrou aqui em 2026-07-28: era escrita direto pelo
# passo "descrever" e destruída pela raspagem seguinte do catálogo (§6.2).
COLS_DERIVADAS = ["bairro", "popularidade", "esgotado", "cancelado",
                  "preco_min", "tem_gratis", "categoria"]

# Colunas de data normalizadas na escrita (invariante do schema: ISO UTC
# "+00:00", via tempo.norm_ts) — é o que torna a comparação lexical segura.
_COLS_DATA = {"start_date", "end_date", "raspado_em"}

# Campos ricos que podem ser colhidos num passo separado do catálogo (o
# "descrever"): no upsert, valor novo NULL preserva o que já está na base.
# ATENÇÃO: COALESCE só protege contra valor novo NULL — nunca contra um valor
# genérico não-nulo. Foi assim que o `event_type`='NORMAL' do Sympla apagava a
# categoria boa a cada rodada.
_COLS_PRESERVAR = {"descricao", "atracoes", "preco_min", "categoria"}


def upsert_eventos(con, eventos):
    """Insere ou atualiza uma lista de eventos normalizados (dicts).

    As colunas de data passam por tempo.norm_ts aqui — é o único ponto de
    escrita, então é ele que garante o invariante do schema (ISO UTC "+00:00",
    comparável lexicalmente).

    As chaves reservadas do dict normalizado não são colunas de eventos:
      _raw   payload bruto  -> cru.<fonte>, origem 'catalogo' (append-only)
      _cru   colunas próprias da tabela de cru (os rótulos que a coleta conhece
             e o payload não diz: cidade_label, estado_label, slug)
    Dicts sem elas seguem funcionando.
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
        if e.get("_raw") is not None and e["fonte"] in gravar.FONTES:
            gravar.gravar(con, e["fonte"], e["id_nativo"], "catalogo",
                          e["_raw"], e["raspado_em"], commit=False,
                          **(e.get("_cru") or {}))
    con.commit()
    return len(eventos)


def agregar(lotes):
    """Colunas de eventos que resumem os lotes. Leitura combinada:
    preco_min=38.99 + tem_gratis=1 -> "grátis em condições, pagos a partir de
    R$ 38,99"; preco_min NULL + tem_gratis=1 -> evento grátis."""
    pagos = [lt["preco"] for lt in lotes
             if not lt["gratis"] and lt["preco"] is not None]
    return {"preco_min": min(pagos) if pagos else None,
            "tem_gratis": 1 if any(lt["gratis"] and lt["esgotado"] != 1
                                   for lt in lotes) else 0,
            "esgotado": 1 if all(lt["esgotado"] == 1 for lt in lotes) else 0}


def ler_cru(con, fonte):
    """Estado corrente de uma fonte no cru, já pareado com o evento na prata.

    Lê a view `_atual` (a versão mais recente de cada id_nativo+origem), não a
    tabela: quem quiser série temporal vai na tabela.
    """
    return con.execute(
        f"SELECT c.id_nativo, c.origem, c.payload, c.api, e.id AS evento_id "
        f"FROM cru.{fonte}_atual c "
        f"JOIN tratado.eventos e ON e.id = %s || c.id_nativo "
        f"ORDER BY c.id_nativo, c.origem", (f"{fonte}:",)).fetchall()


def aplicar(con):
    """Reseta e recalcula colunas derivadas e lotes a partir do `cru`.

    Idempotente e a seco: cada execução zera as colunas derivadas, apaga os
    lotes e recalcula tudo do zero a partir do bruto guardado. Derivações do
    mesmo evento nunca disputam coluna (cada origem preenche colunas
    distintas), então a ordem entre as fontes não importa.

    Retorna {coluna: quantos eventos ganharam valor} + "lotes" com o total.
    """
    con.execute("UPDATE tratado.eventos SET "
                + ", ".join(f"{c} = NULL" for c in COLS_DERIVADAS))
    con.execute("DELETE FROM tratado.lotes")
    contagem = dict.fromkeys(COLS_DERIVADAS, 0)
    contagem["lotes"] = 0

    for fonte, modulo in TRILHAS.items():
        for r in ler_cru(con, fonte):
            derivacao = modulo.DERIVACOES.get(r["origem"])
            extrator = modulo.LOTES.get(r["origem"])
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
                        "INSERT INTO tratado.lotes (evento_id, ordem, nome, "
                        "preco, taxa, gratis, esgotado) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        [(r["evento_id"], i, lt["nome"], lt["preco"],
                          lt["taxa"], 1 if lt["gratis"] else 0, lt["esgotado"])
                         for i, lt in enumerate(lotes)])
                    contagem["lotes"] += len(lotes)
                    campos.update({c: v for c, v in agregar(lotes).items()
                                   if v is not None})
            if not campos:
                continue
            con.execute(
                "UPDATE tratado.eventos SET "
                + ", ".join(f"{c} = %s" for c in campos) + " WHERE id = %s",
                [*campos.values(), r["evento_id"]])
            for c in campos:
                contagem[c] += 1
    con.commit()
    return contagem
