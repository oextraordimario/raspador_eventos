# Pesquisa — como um terceiro conecta este MCP (clientes, auth, provedores)

> Anexo da spec `spec.md` (NI-11). **Levantado em 2026-07-14** a partir da
> documentação oficial dos clientes e provedores. É o que sustenta as decisões
> da spec — em especial a de **abandonar o token na URL em favor de OAuth**. Se
> algum destes fatos mudar, a decisão merece ser reaberta.

## 1. A pergunta

O MCP remoto está no ar desde a Fase 0b (NI-20), mas foi validado com **um**
usuário: o autor, com um prefixo de rota secreto. Antes de abrir a terceiros:
**quem consegue plugar isso, a que custo, e como se autoriza uma pessoa?**

## 2. Quem consegue instalar um connector personalizado

| Cliente | Connector MCP personalizado? | Plano exigido | Gesto do usuário |
|---|---|---|---|
| **Claude** (web, celular, desktop) | Sim | **Free serve** — limitado a **1** connector personalizado; Pro/Max sem limite. Em Team/Enterprise, só o Owner adiciona | *Configurações → Conectores → Adicionar conector personalizado* → colar a URL |
| **ChatGPT** | Sim, via **Developer Mode** | **Plus, Pro, Business, Enterprise ou Edu** — Free e Go **não têm** | Ativar Developer Mode + cadastrar o connector |
| **Gemini** (app consumidor) | **Não** | — | Não existe. Só Gemini Enterprise (Data Store) e Gemini CLI (arquivo de config) |
| Outros (Cursor, Codex, Claude Code) | Sim | — | Arquivo de config — público de dev |

**Conclusões:** o canal é **Claude**, e o gargalo não é dinheiro (conta grátis
pluga). ChatGPT tem dois filtros em cima (plano pago + Developer Mode) e o
Gemini do dia a dia simplesmente não fala MCP — um botão "conectar ao Gemini"
não teria para onde apontar. Como o transporte é o mesmo, quem tiver ChatGPT
Plus e quiser pluga a mesma URL; não é o público do convite.

## 3. Não existe "botão instalar" partindo do nosso site

Não há deep link oficial documentado que pré-preencha um connector
personalizado no Claude. O que existe:

- o modal de adicionar connector é endereçável
  (`https://claude.ai/settings/connectors?modal=add-custom-connector`) — não é
  documentado como API pública, então serve de atalho, **não** de contrato;
- o **Connector Directory** da Anthropic — aí sim vira um "Connect" de um
  clique, mas passa por **revisão** deles (`mcp-review@anthropic.com`).

Ou seja: **o gesto de colar a URL permanece**, com ou sem OAuth. O que a landing
page (spec §7) faz é levar a pessoa até lá com a URL no clipboard e o passo a
passo — e o que o OAuth muda é tudo o que acontece **depois** de colar.

## 4. Autorização — o que o Claude suporta (e o que ele desaconselha)

Da doc oficial ([Authentication for connectors](https://claude.com/docs/connectors/building/authentication)):

| Tipo | O que é | Disponibilidade |
|---|---|---|
| `oauth_dcr` | OAuth 2.0 + **Dynamic Client Registration** (RFC 7591) | **Pronto, out of the box** |
| `oauth_cimd` | OAuth 2.0 + Client ID Metadata Document | Pronto (spec de 2025-11) |
| `oauth_anthropic_creds` | Credenciais de cliente guardadas pela Anthropic | Sob contato (`mcp-review@`) |
| `static_headers` | Credencial fixa em header, **cadastrada pelo admin da organização** | Beta — compartilhada pela org, **não** por pessoa |
| `none` | Sem auth (servidor aberto) | Suportado |

**O achado que matou a v1 desta spec:** a doc afirma que token/API key **na URL
do connector** (`?token=`, `?apiKey=`…) **não é recomendado** — "URLs são
rotineiramente gravadas em logs de servidor, proxies e histórico de navegação,
então uma credencial em query string é fácil de vazar" — e que a **spec de
authorization do MCP proíbe access token na query string**. A v1 punha o token
no *path* em vez da query, mas a objeção é a mesma. Some-se que um token opaco
não diz **quem** é a pessoa, e o caso do OAuth fecha sozinho.

`static_headers` não é a saída: é credencial **de organização**, cadastrada por
admin — não existe no fluxo de um amigo com conta pessoal.

### Requisitos concretos do fluxo OAuth (o que o Claude exige)

- **PKCE S256 em toda autorização** — o servidor de autorização precisa suportar
  e anunciar `code_challenge_methods_supported: ["S256"]`.
- **`401` com `WWW-Authenticate: Bearer resource_metadata="…"`** apontando para o
  documento de *protected resource metadata* (RFC 9728). O `401` é obrigatório —
  o Claude **não** honra o header numa resposta `200`.
- O campo **`resource` do metadata tem que bater exatamente com a URL que o
  usuário digita** no Claude, path incluído.
- `authorization_servers` aponta o issuer; o AS serve a própria discovery em
  `/.well-known/` (RFC 8414 ou OIDC Discovery).
- Redirect URI a registrar: `https://claude.ai/api/mcp/auth_callback` (as
  superfícies hospedadas). O Claude Code usa loopback com porta efêmera.
- Timeouts: **10 s** para discovery/registro/token, 30 s para refresh.
- Tráfego de saída da Anthropic vem de `160.79.104.0/21` (relevante se houver WAF).

## 5. Provedores de OAuth (quem faz o trabalho pesado por nós)

Escrever um Authorization Server (DCR + PKCE + `/authorize` + `/token` + rotação
de refresh + metadata) é código de segurança — errar é caro. Provedores que já
falam MCP:

| Provedor | MCP/DCR | Free tier | Nota |
|---|---|---|---|
| **WorkOS AuthKit** | Doc de MCP própria; **DCR liga com um toggle** no dashboard (Connect → Configuration), com escolha dos escopos padrão | **1M MAU** | Escolhido na spec §3 |
| **Auth0** | "Auth for MCP" em GA; DCR suportado, mas eles **recomendam CIMD** e o setup tem mais peças | 25k MAU | Fallback |
| Stytch | Connected Apps foi feito para isso (DCR, MCP) | sim | Adquirida pela Twilio (2025-11) — risco de foco |
| Descope, Scalekit, Clerk | suporte anunciado | varia | Não avaliados a fundo |

## 6. Fontes

- [Claude — Authentication for connectors](https://claude.com/docs/connectors/building/authentication) (tipos de auth, proibição de credencial na URL, requisitos do 401/PKCE/callback)
- [Claude — Get started with custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- [Claude — Use connectors to extend Claude's capabilities](https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities) (planos)
- [OpenAI — Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
- [Gemini Apps Community — MCP no app consumidor](https://support.google.com/gemini/thread/364779684/does-gemini-chat-support-mcp-custom-connectors?hl=en) e [Gemini Enterprise — custom MCP server](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/custom-mcp-server/set-up-custom-mcp-server)
- [WorkOS — AuthKit + MCP](https://workos.com/docs/authkit/mcp) e [DCR no MCP](https://workos.com/blog/dynamic-client-registration-dcr-mcp-oauth)
- [Auth0 — Auth for MCP em GA](https://auth0.com/blog/auth0-auth-for-mcp-servers-generally-available/)
