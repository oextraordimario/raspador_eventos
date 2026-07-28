"""Entrypoint serverless (Vercel) do MCP remoto — Fase 0b (NI-20) + OAuth (NI-11).

A Vercel serve funções Python da pasta api/; esta expõe o app ASGI do FastMCP
(streamable HTTP, stateless). O caminho vem das envs, e é ele que o vercel.json
precisa reescrever para cá:

- com OAuth: AUTHKIT_ISSUER + MCP_RECURSO → o caminho sai de MCP_RECURSO
  (/mcp), e o FastMCP publica junto a rota de metadados da RFC 9728,
  /.well-known/oauth-protected-resource/mcp;
- sem OAuth: MCP_SEGREDO → /<segredo>/mcp, o modo da Fase 0b.

Envs exigidas no host: EVENTOS_DB_URL (URL pooled do Neon) + um dos dois modos.
Specs: docs/specs/20260711_consulta-na-nuvem/, 20260726_abrir-ao-publico/.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

from servico.mcp_server import mcp  # noqa: E402  (precisa do sys.path acima)

_recurso = os.environ.get("MCP_RECURSO")
_segredo = os.environ.get("MCP_SEGREDO")
if _recurso:
    _caminho = urlparse(_recurso).path or "/mcp"
elif _segredo:
    _caminho = f"/{_segredo}/mcp"
else:
    raise RuntimeError("Defina AUTHKIT_ISSUER + MCP_RECURSO (OAuth) ou "
                       "MCP_SEGREDO (prefixo secreto) nas envs do host.")

# A proteção de DNS rebinding do SDK só aceita localhost por default e devolvia
# 421 pro Host da Vercel. Ela protege servidor LOCAL contra browser de vítima;
# aqui o host é público atrás de HTTPS e o gate é o token — desligar.
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False)
mcp.settings.stateless_http = True
mcp.settings.streamable_http_path = _caminho
app = mcp.streamable_http_app()
