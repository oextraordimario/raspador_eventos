"""Registro da rodada em `operacao.execucoes` — observabilidade (NI-19).

Uma linha por execução do pipeline, para o relatório comparar com a rodada
anterior e alertar queda de coleta: scraper quebrado em silêncio é a hipótese
de risco nº 1 do produto.

Mora em `pipeline/` porque é a orquestração registrando a si mesma — não é dado
de fonte (não é `cru`) nem se reconstrói de nada (não é `tratado`).
"""

import json


def registrar_execucao(con, iniciada_em, duracao_s, modo, fontes, passos, erros):
    """Grava o resumo de uma rodada.

    fontes/passos/erros são estruturas Python; viram JSON aqui.
    """
    con.execute(
        "INSERT INTO operacao.execucoes (iniciada_em, duracao_s, modo, fontes, "
        "passos, erros) VALUES (%s, %s, %s, %s, %s, %s)",
        (iniciada_em, duracao_s, modo,
         *(json.dumps(x, ensure_ascii=False) for x in (fontes, passos, erros))))
    con.commit()


def registrar_coleta(con, fonte, iniciada_em, terminada_em, resultado):
    """Grava UMA coleta de UMA fonte em `operacao.coletas`.

    É a mesma informação que vai em `execucoes.fontes`, mas consultável em SQL —
    e é dela que `tratamento/sumido.py` deriva a coluna `sumido`. O
    `iniciada_em` é a âncora: o instante em que a raspagem daquela fonte
    começou, e não o fim (evento raspado no meio da rodada tem raspado_em entre
    os dois).
    """
    con.execute(
        "INSERT INTO operacao.coletas (fonte, iniciada_em, terminada_em, "
        "coletados, total_site, erro) VALUES (%s, %s, %s, %s, %s, %s)",
        (fonte, iniciada_em, terminada_em, resultado.get("coletados"),
         resultado.get("total_site"), resultado.get("erro")))
    con.commit()


def ultima_execucao(con):
    """Última rodada registrada (dict com fontes/passos/erros já
    desserializados) ou None. É a base da comparação 'vs. rodada anterior'."""
    r = con.execute("SELECT * FROM operacao.execucoes "
                    "ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("fontes", "passos", "erros"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d
