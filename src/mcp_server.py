"""MCP server que expõe a base unificada de eventos como tools para um agente de IA.

Transporte stdio — compatível com Claude Code, Claude Desktop e Codex.
As tools são finas: delegam para a camada de consulta (consulta.py).

Rodar manualmente (para depurar): python src/mcp_server.py
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
    cidade e período. Todos os argumentos são opcionais. A base já vem limpa:
    anúncios/cursos, eventos cancelados e eventos que sumiram do catálogo da
    fonte (provável cancelamento silencioso) são filtrados, e o mesmo evento
    publicado em mais de uma plataforma vem colapsado num único resultado
    (campo outras_urls traz os links dele nas demais plataformas, quando
    houver).

    Args:
        texto: termos de busca no nome, atrações e descrição do evento (sintaxe
            FTS5, ex.: "pagode", "funk OR techno", "eletrônica"). Acha o termo
            mesmo quando ele só aparece na descrição. Vazio = qualquer evento.
        cidade: cidade do evento (padrão "Brasília"; hoje a base só cobre Brasília).
        data_inicio: início da janela, ISO 8601 (ex.: "2026-07-10T00:00:00+00:00").
            Vazio = sem limite inferior. Para "só eventos futuros", passe o horário
            atual — obtenha-o com a tool data_atual.
        data_fim: fim da janela, ISO 8601. Vazio = sem limite superior.
        limite: número máximo de resultados (padrão 20), ordenados por data.

    Returns:
        Lista de eventos com nome, fonte, start_date, end_date, cidade, local,
        bairro, categoria, organizador, url, atracoes (line-up), preco_min
        (menor lote PAGO, em R$ totais com taxa; null = sem lote pago ou fonte
        não informou), tem_gratis (1 = há lote grátis disponível — cortesia,
        entrada franca; junto com preco_min null significa evento grátis),
        esgotado (1 = sem ingressos disponíveis), popularidade (score de
        trending da fonte — quanto maior, mais em alta; null fora do Sympla),
        descricao (trecho inicial) e outras_urls (links do mesmo evento em
        outras plataformas, se houver). Para preço detalhado por lote ou a
        descrição completa de um evento, chame detalhar_evento com a url.
    """
    return consulta.buscar_eventos(
        texto=texto or None, cidade=cidade or None,
        data_inicio=data_inicio or None, data_fim=data_fim or None,
        limite=limite)


@mcp.tool()
def detalhar_evento(url: str) -> dict:
    """Detalha UM evento da base: descrição completa (sem o corte da busca) e
    a tabela de lotes de ingresso. Use depois de buscar_eventos, com a url
    exata que ela devolveu, quando o usuário quiser aprofundar um evento —
    "me conta mais dessa festa", "quanto custa pra homem?", "tem cortesia?".

    Cada lote traz nome (cru, como a fonte publica), preco (R$ TOTAL a pagar,
    taxa já embutida), taxa (a parcela de taxa, quando a fonte separa), gratis
    (1 = cortesia/entrada franca) e esgotado (1 = lote sem estoque/encerrado).
    As condições do lote estão no NOME — "CORTESIA FEMININA DA COPA ATÉ 00H",
    "MASCULINO 2º LOTE", "meia-entrada" — leia-os para responder preço com
    precisão (ex.: "grátis para mulheres até 00h; masculino a partir de
    R$ 45 + 4,50 de taxa").

    Args:
        url: a url do evento, exatamente como veio de buscar_eventos.

    Returns:
        Dict único com os campos da busca + descricao completa + lotes
        (lista, na ordem de exibição da fonte), ou {"erro": ...} se a url
        não estiver na base.
    """
    return consulta.detalhar_evento(url)


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
