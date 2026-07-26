"""Verificação do token OAuth do MCP remoto (NI-11).

Este servidor é **resource server**, nunca authorization server: quem emite,
renova e revoga token é o AuthKit (WorkOS). Aqui só se confere a assinatura —
não há segredo de cliente, tela de login nem sessão do nosso lado.

O cliente MCP executa o fluxo inteiro sozinho, sem nada codificado aqui:

1. chama `/mcp` sem token e leva 401 com `WWW-Authenticate` apontando para
   `/.well-known/oauth-protected-resource/mcp` (o FastMCP serve essa rota);
2. lê ali o issuer do AuthKit e descobre os endpoints dele;
3. registra-se sozinho — DCR ou CIMD, ambos habilitados no AuthKit — e faz o
   authorization code flow com PKCE;
4. volta com `Authorization: Bearer <jwt>`.

A chave pública sai do JWKS do issuer. O `PyJWKClient` mantém cache, então a
busca de rede acontece uma vez por instância fria da função serverless.
"""

import sys

import anyio.to_thread
import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken


class VerificadorAuthKit:
    """`TokenVerifier` do SDK: devolve `AccessToken` se o JWT confere, senão None.

    Devolver None é o contrato — é o que faz o SDK responder 401 com o
    `WWW-Authenticate` que dispara o passo 1 acima. Por isso nenhuma falha de
    validação vira exceção: exceção viraria 500 e o cliente nunca descobriria
    que só precisava se autenticar.
    """

    def __init__(self, issuer: str, recurso: str):
        self.issuer = issuer.rstrip("/")
        self.recurso = recurso
        self._jwks = PyJWKClient(f"{self.issuer}/oauth2/jwks")

    def _verificar(self, token: str) -> AccessToken | None:
        try:
            chave = self._jwks.get_signing_key_from_jwt(token).key
            # `audience` é o controle que impede um token emitido para OUTRO
            # resource server do mesmo AuthKit de valer aqui. O AuthKit
            # preenche o aud com o resource indicator que o cliente pediu — o
            # mesmo URI registrado em Connect → Configuration.
            claims = jwt.decode(token, chave, algorithms=["RS256"],
                                audience=self.recurso, issuer=self.issuer)
        except Exception as e:  # noqa: BLE001
            # O motivo tem que aparecer no log do host: token recusado é
            # indepurável de fora, porque o cliente MCP só mostra "unauthorized".
            print(f"[auth] token recusado: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return None

        return AccessToken(
            token=token,
            client_id=claims.get("client_id") or claims.get("azp") or "",
            subject=claims.get("sub"),
            scopes=(claims.get("scope") or "").split(),
            expires_at=claims.get("exp"),
            resource=self.recurso,
            claims=claims,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        # Busca do JWKS (rede, só na 1ª chamada da instância) e verificação de
        # assinatura (CPU) são ambas síncronas — fora da thread do event loop.
        return await anyio.to_thread.run_sync(self._verificar, token)
