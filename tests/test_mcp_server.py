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
SERVER = RAIZ / "src" / "mcp_server.py"

sys.path.insert(0, str(RAIZ / "src"))
import enriquecer  # noqa: E402  (p/ conferir que ruído não vaza pela tool)


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
            assert {"buscar_eventos", "detalhar_evento", "buscar_filmes",
                    "sessoes_filme", "data_atual"} <= tools, "faltam tools"

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

            # ruído (anúncio/curso) não pode vazar pela tool
            vazados = [e["nome"] for e in eventos + fim_semana
                       if enriquecer._RUIDO_RE.search(
                           enriquecer._normalizar_texto(e["nome"]))]
            assert not vazados, f"ruído vazou pela tool: {vazados}"
            print("nenhum nome de ruído nas respostas (ok)")

            # caso vazio
            vazio = dados(await session.call_tool(
                "buscar_eventos", {"texto": "xyzzyabracadabra123"}))
            assert vazio == []
            print("busca sem correspondência: 0 (ok)")

            # detalhar_evento: descrição completa + lotes de um evento real
            alvo = next(e for e in fim_semana + eventos if e.get("url"))
            det = dados(await session.call_tool("detalhar_evento",
                                                {"url": alvo["url"]}))
            assert det.get("nome") and "lotes" in det and "descricao" in det, det
            print(f"detalhar_evento('{alvo['nome'][:35]}'): "
                  f"{len(det['lotes'])} lotes | "
                  f"descrição {len(det['descricao'] or '')} chars")
            erro = dados(await session.call_tool(
                "detalhar_evento", {"url": "https://nao-existe.example/x"}))
            assert "erro" in erro, erro
            print("detalhar_evento(url desconhecida): erro amigável (ok)")

            # cinema: filmes em cartaz + sessões de um filme real
            filmes = dados(await session.call_tool("buscar_filmes", {}))
            assert filmes, "esperava >=1 filme em cartaz (rodou o atualizar?)"
            assert {"titulo", "sessoes", "cinemas"} <= set(filmes[0]), filmes[0]
            print(f"buscar_filmes(): {len(filmes)} filmes | "
                  f"ex: {filmes[0]['titulo'][:35]} "
                  f"({filmes[0]['sessoes']} sessões)")
            sf = dados(await session.call_tool(
                "sessoes_filme", {"filme": filmes[0]["titulo"]}))
            assert sf.get("id") and sf["sessoes"], sf
            s0 = sf["sessoes"][0]
            assert {"cinema", "inicio", "tipos"} <= set(s0), s0
            print(f"sessoes_filme('{filmes[0]['titulo'][:30]}'): "
                  f"{len(sf['sessoes'])} sessões | 1ª: {s0['inicio'][:16]} "
                  f"{s0['cinema']} ({s0['tipos']})")
            erro = dados(await session.call_tool(
                "sessoes_filme", {"filme": "xyzzyfilmeinexistente"}))
            assert "erro" in erro, erro
            print("sessoes_filme(filme desconhecido): erro amigável (ok)")

    print("\nOK — MCP server responde como cliente real espera.")


if __name__ == "__main__":
    asyncio.run(main())
