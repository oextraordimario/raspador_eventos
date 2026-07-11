"""Entrypoint serverless (Vercel) do MCP remoto — Fase 0b (NI-20).

A Vercel serve funções Python da pasta api/; esta expõe o app ASGI do FastMCP
(streamable HTTP, stateless) sob o prefixo secreto MCP_SEGREDO. O vercel.json
reescreve TODAS as rotas para cá — o que não bater em /<segredo>/mcp cai no 404
do próprio app. O modo local/stdio continua em src/mcp_server.py.

Envs exigidas no host: EVENTOS_DB_URL (URL pooled do Neon) e MCP_SEGREDO.
Spec: docs/specs/20260711_consulta-na-nuvem/.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

from mcp_server import mcp  # noqa: E402  (precisa do sys.path acima)

_segredo = os.environ.get("MCP_SEGREDO")
if not _segredo:
    raise RuntimeError("Defina a env MCP_SEGREDO no host (prefixo secreto da URL).")

# A proteção de DNS rebinding do SDK só aceita localhost por default e devolvia
# 421 pro Host da Vercel. Ela protege servidor LOCAL contra browser de vítima;
# aqui o host é público atrás de HTTPS e o gate é o prefixo secreto — desligar.
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False)
mcp.settings.stateless_http = True
mcp.settings.streamable_http_path = f"/{_segredo}/mcp"
app = mcp.streamable_http_app()
