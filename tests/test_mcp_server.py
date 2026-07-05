"""Teste de fumaça do MCP server: sobe o server via stdio e age como um cliente
MCP real (mesmo caminho que Claude Code / Claude Desktop / Codex usam).

Uso: python tests/test_mcp_server.py
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parent.parent
SERVER = RAIZ / "mcp_server.py"


def dados(result):
    """Extrai o payload de um CallToolResult, lidando com os dois formatos do
    FastMCP: listas vêm em structuredContent["result"] (e um bloco de content por
    item); dicts vêm como bloco único de content."""
    sc = result.structuredContent
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]
    if sc is not None:
        return sc
    blocos = [json.loads(c.text) for c in result.content if getattr(c, "text", None)]
    return blocos[0] if len(blocos) == 1 else blocos


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = {t.name for t in (await session.list_tools()).tools}
            print("tools expostas:", sorted(tools))
            assert {"buscar_eventos", "data_atual"} <= tools, "faltam tools"

            # data_atual
            da = dados(await session.call_tool("data_atual", {}))
            print("data_atual:", da["data"], "|", da["dia_semana"])

            agora = datetime.now(timezone.utc).isoformat()

            # busca com texto + janela futura
            eventos = dados(await session.call_tool(
                "buscar_eventos",
                {"texto": "pagode", "cidade": "Brasília", "data_inicio": agora}))
            print(f"buscar_eventos('pagode', futuros): {len(eventos)} eventos")
            assert eventos, "esperava >=1 evento de pagode"
            assert isinstance(eventos[0], dict) and "nome" in eventos[0]
            print("  ex:", eventos[0]["nome"][:45], "|", eventos[0]["fonte"])

            # janela do fim de semana (usa a saída de data_atual)
            fds = da["fim_de_semana"]
            fim_semana = dados(await session.call_tool(
                "buscar_eventos",
                {"data_inicio": fds["inicio"], "data_fim": fds["fim"], "limite": 100}))
            print(f"buscar_eventos(fim de semana {fds['inicio'][:10]}"
                  f"..{fds['fim'][:10]}): {len(fim_semana)} eventos")

            # caso vazio
            vazio = dados(await session.call_tool(
                "buscar_eventos", {"texto": "xyzzyabracadabra123"}))
            assert vazio == []
            print("busca sem correspondência: 0 (ok)")

    print("\nOK — MCP server responde como cliente real espera.")


if __name__ == "__main__":
    asyncio.run(main())
