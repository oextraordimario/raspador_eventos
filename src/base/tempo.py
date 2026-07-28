"""Parse único das datas ISO das fontes (formatos mistos).

Sympla/Ingresse gravam "+00:00", Shotgun grava ".000Z"; comparação lexical
dessas strings falha entre fontes. Este módulo é a única implementação do
parse (antes triplicada em atualizar/enriquecer/consulta): tudo vira UTC
antes de comparar. Sem timezone na origem = assume UTC.
"""

from datetime import datetime, timezone


def instante(iso):
    """Data ISO (qualquer formato das fontes) -> datetime UTC; None se não parsear."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def norm_ts(iso):
    """Data ISO -> texto ISO UTC comparável/ordenável; None se não parsear.

    Aplicada pelo comum.upsert_eventos na ESCRITA (invariante do schema:
    start_date/end_date/raspado_em sempre em ISO UTC "+00:00") e pela
    consulta.py nos parâmetros de data — assim a comparação no SQL é lexical
    e segura, sem função registrada em runtime.
    """
    dt = instante(iso)
    return dt.isoformat() if dt else None
