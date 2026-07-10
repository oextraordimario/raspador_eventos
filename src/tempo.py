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

    Registrada como função SQL `norm_ts` pela consulta.py (comparações de
    start_date no SQLite).
    """
    dt = instante(iso)
    return dt.isoformat() if dt else None
