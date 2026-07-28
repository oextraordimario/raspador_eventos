"""Reaplica as decisões humanas (`curado.correcoes`) sobre a prata.

O tratamento reescreve `tratado` do zero a cada rodada. Sem este passo,
qualquer correção feita à mão sobrevive até a próxima rodada e some — que é
exatamente o que acontece hoje se alguém consertar um nome no DBeaver.

ORDEM IMPORTA, e em dois pontos só:
  * roda DEPOIS do enriquecer, porque a curadoria precisa poder DERRUBAR uma
    decisão dele (desfazer um dedupe errado, tirar um `ruido` que era falso
    positivo);
  * roda ANTES do FTS, para a busca indexar o texto já corrigido.
"""

import json

# Allowlist do que uma pessoa pode corrigir. `id`, `fonte` e `busca` NUNCA
# entram: os dois primeiros são identidade (mudá-los cria um registro fantasma
# que a próxima rodada recria), e `busca` é derivada — corrigi-la seria
# corrigir o sintoma. `dedupe_grupo`/`dedupe_canonico` entram porque desfazer
# um agrupamento errado é o caso de curadoria mais comum que a base tem hoje.
CURAVEIS = {
    "nome", "local_nome", "endereco", "bairro", "categoria", "organizador",
    "atracoes", "descricao", "start_date", "end_date", "cidade", "estado",
    "url", "imagem", "preco_min", "tem_gratis", "esgotado",
    "ruido", "ruido_motivo", "cancelado", "sumido",
    "dedupe_grupo", "dedupe_canonico",
}


def validar(valores):
    """Levanta se a correção mexe em campo fora da allowlist."""
    fora = set(valores) - CURAVEIS
    if fora:
        raise ValueError(
            f"campos não curáveis: {sorted(fora)}. Curáveis: "
            f"{sorted(CURAVEIS)}")
    if not valores:
        raise ValueError("correção vazia")


def aplicar(con):
    """Aplica todas as correções ATIVAS sobre tratado.eventos.

    Retorna {"aplicadas": n, "orfas": n} — órfã é a correção cujo registro não
    existe mais na prata (some da consulta, mas continua na tabela e aparece em
    curado.pendencias: correção não se apaga).
    """
    aplicadas = orfas = 0
    for r in con.execute(
            "SELECT id, registro_id, valores FROM curado.correcoes "
            "WHERE revogada_em IS NULL AND entidade = 'eventos' "
            "ORDER BY id").fetchall():
        valores = r["valores"]
        if isinstance(valores, str):          # psycopg devolve dict p/ jsonb
            valores = json.loads(valores)
        try:
            validar(valores)
        except ValueError:
            # Correção gravada antes de a allowlist existir, ou por outra
            # ferramenta: ignora os campos proibidos em vez de derrubar a
            # rodada inteira por causa de uma linha.
            valores = {k: v for k, v in valores.items() if k in CURAVEIS}
            if not valores:
                continue
        cur = con.execute(
            "UPDATE tratado.eventos SET "
            + ", ".join(f"{c} = %s" for c in valores) + " WHERE id = %s",
            [*valores.values(), r["registro_id"]])
        if cur.rowcount:
            aplicadas += 1
        else:
            orfas += 1
    # Sem commit: o ciclo inteiro do tratamento roda numa transação só
    # (tratamento/ciclo.py) — ver o cabeçalho de lá.
    return {"aplicadas": aplicadas, "orfas": orfas}


def locais_canonicos(con):
    """{grafia normalizada: nome canônico} de curado.locais, para o dedupe.

    Complementa (não substitui) os `local_aliases` da watchlist do Instagram:
    aquilo é configuração de ENTRADA, isto é referência sobre entidades do
    mundo. Spec §4.3.
    """
    saida = {}
    for r in con.execute("SELECT nome, aliases FROM curado.locais"):
        saida[r["nome"]] = r["nome"]
        for a in (r["aliases"] or []):
            saida[a] = r["nome"]
    return saida


def nomes_df(con):
    """Nomes de locais marcados como do DF — o que ancora o filtro `_do_df` do
    Ticket and Go. A COLETA recebe isto pronto, para não precisar conhecer a
    base."""
    nomes = set()
    for r in con.execute("SELECT nome, aliases FROM curado.locais "
                         "WHERE no_df"):
        nomes.add(r["nome"])
        nomes.update(r["aliases"] or [])
    return nomes


def pendencias(con, limite=None):
    """A fila de curadoria (view curado.pendencias), agrupada por tipo."""
    sql = "SELECT tipo, registro_id, detalhe, porque FROM curado.pendencias"
    if limite:
        sql += f" LIMIT {int(limite)}"
    return [dict(r) for r in con.execute(sql)]
