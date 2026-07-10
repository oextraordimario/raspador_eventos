"""Derivação a seco: (re)calcula colunas de eventos a partir do payload bruto.

Lê a camada Bronze (eventos_raw) e preenche as colunas derivadas de eventos —
sem nenhuma requisição de rede. Campo novo do schema vira uma função aqui e um
`python src/atualizar.py --so-derivar`, em vez de re-raspar tudo.

Idempotente como o enriquecer: cada execução reseta as colunas derivadas e
recalcula do zero a partir do bruto guardado.

Campo-prova da 1ª entrega (docs/specs/20260710_camada-bronze/spec.md): bairro,
do location.neighborhood do catálogo do Sympla (~48% dos eventos têm). Ainda
sem uso na consulta — produto decide depois.
"""

import json

# Colunas de eventos preenchidas por este módulo (resetadas a cada aplicar()).
COLS_DERIVADAS = ["bairro"]


def _sympla_catalogo(p):
    bairro = ((p.get("location") or {}).get("neighborhood") or "").strip()
    return {"bairro": bairro or None}


# (fonte, origem) -> função payload -> {coluna: valor}; valor None é ignorado
# (não sobrescreve o que outra derivação tiver preenchido).
_DERIVACOES = {
    ("sympla", "catalogo"): _sympla_catalogo,
}


def aplicar(con):
    """Reseta e recalcula as colunas derivadas a partir de eventos_raw.

    Retorna {coluna: quantos eventos ganharam valor}, para o relatório.
    """
    con.execute("UPDATE eventos SET " +
                ", ".join(f"{c} = NULL" for c in COLS_DERIVADAS))
    contagem = dict.fromkeys(COLS_DERIVADAS, 0)
    rows = con.execute(
        "SELECT r.evento_id, r.origem, r.payload, e.fonte "
        "FROM eventos_raw r JOIN eventos e ON e.id = r.evento_id").fetchall()
    for r in rows:
        derivacao = _DERIVACOES.get((r["fonte"], r["origem"]))
        if not derivacao:
            continue
        campos = {c: v for c, v in derivacao(json.loads(r["payload"])).items()
                  if v is not None}
        if not campos:
            continue
        con.execute(
            "UPDATE eventos SET " + ", ".join(f"{c} = ?" for c in campos) +
            " WHERE id = ?", [*campos.values(), r["evento_id"]])
        for c in campos:
            contagem[c] += 1
    con.commit()
    return contagem
