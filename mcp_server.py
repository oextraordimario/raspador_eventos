"""MCP server que expõe a base unificada de eventos como tools para um agente de IA.

Transporte stdio — compatível com Claude Code, Claude Desktop e Codex.
As tools são finas: delegam para a camada de consulta (consulta.py).

Rodar manualmente (para depurar): python mcp_server.py
Em uso normal, quem executa é o cliente de IA, via a config de MCP.
"""

from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

import consulta

mcp = FastMCP("eventos-brasilia")

_DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"]


@mcp.tool()
def buscar_eventos(texto: str = "", cidade: str = "Brasília",
                   data_inicio: str = "", data_fim: str = "",
                   limite: int = 20) -> list[dict]:
    """Busca festas, baladas e shows em Brasília na base unificada (Sympla,
    Ingresse e Shotgun). Use para responder o que há de festa/balada/show numa
    cidade e período. Todos os argumentos são opcionais.

    Args:
        texto: termos de busca no nome/categoria do evento (sintaxe FTS5, ex.:
            "pagode", "funk OR techno", "sertanejo"). Vazio = qualquer evento.
        cidade: cidade do evento (padrão "Brasília"; hoje a base só cobre Brasília).
        data_inicio: início da janela, ISO 8601 (ex.: "2026-07-10T00:00:00+00:00").
            Vazio = sem limite inferior. Para "só eventos futuros", passe o horário
            atual — obtenha-o com a tool data_atual.
        data_fim: fim da janela, ISO 8601. Vazio = sem limite superior.
        limite: número máximo de resultados (padrão 20), ordenados por data.

    Returns:
        Lista de eventos com nome, fonte, start_date, end_date, cidade, local,
        categoria, organizador e url.
    """
    return consulta.buscar_eventos(
        texto=texto or None, cidade=cidade or None,
        data_inicio=data_inicio or None, data_fim=data_fim or None,
        limite=limite)


@mcp.tool()
def data_atual() -> dict:
    """Retorna a data/hora atual (UTC) e a janela do fim de semana corrente/próximo.
    Útil para montar filtros como "hoje", "neste fim de semana" ou "sexta que vem"
    antes de chamar buscar_eventos.
    """
    agora = datetime.now(timezone.utc)
    wd = agora.weekday()  # segunda=0 ... domingo=6
    # sexta do fim de semana corrente (se já é sex/sáb/dom) ou do próximo.
    desloc = -(wd - 4) if wd >= 4 else (4 - wd)
    sexta = (agora + timedelta(days=desloc)).replace(
        hour=18, minute=0, second=0, microsecond=0)
    domingo = (sexta + timedelta(days=2)).replace(
        hour=23, minute=59, second=59, microsecond=0)
    return {
        "agora": agora.isoformat(),
        "data": agora.date().isoformat(),
        "dia_semana": _DIAS_PT[wd],
        "fim_de_semana": {"inicio": sexta.isoformat(), "fim": domingo.isoformat()},
    }


if __name__ == "__main__":
    mcp.run()
