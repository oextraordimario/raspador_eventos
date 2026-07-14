# Spec — Abrir o MCP remoto ao público, com OAuth (NI-11)

> **Status:** APROVADA (v2, 2026-07-14) — revisada pelo autor; implementação não
> começou. Três escolhas foram **confirmadas por ele** na revisão e não são mais
> pergunta em aberto:
> 1. **Acesso aberto** a quem logar (sem allowlist nem fila de aprovação) —
>    controle reativo: teto por usuário + bloqueio (§3, §6).
> 2. **Guardar e-mail e nome** vindos do login, com o aviso na landing (§8).
> 3. **NI-10 (cron no GitHub Actions) antes da divulgação** — não bloqueia a
>    implementação desta spec, bloqueia abrir o link (§10).
>
> **O quê/por quê:** PRD §4 (anéis de descoberta) e §6 Fase 1. O MCP remoto de
> hoje (NI-20) é de **uso próprio**: a autorização é um prefixo de rota secreto
> único (`MCP_SEGREDO`), que não distingue pessoas, não se revoga
> individualmente e não registra nada. Abrir nesse estado seria distribuir a
> mesma chave para todo mundo e ficar cego quanto ao uso — e o critério da Fase 1
> ("um conhecido usa") não fecha sem registro (PRD §10).
> **Anexo:** `pesquisa-clientes-mcp.md` — quem consegue instalar um connector, o
> que o Claude exige de auth, e quais provedores existem (levantamento de
> 2026-07-14). É o que sustenta as decisões abaixo.

---

## 0. A v1 desta spec (token na URL) foi descartada — registro

A primeira versão dava **um token por pessoa no path da URL**
(`https://host/<token>/mcp`), validado contra uma tabela `convites`. Morreu ao
ler a documentação de auth do Claude (anexo §4):

- a Anthropic **desaconselha explicitamente** credencial na URL do connector, e a
  spec de authorization do MCP **proíbe** access token em query string — o motivo
  vale igual para o path: URL vaza em log, proxy e histórico;
- um token opaco não diz **quem** é a pessoa: a instrumentação da Fase 1 ficaria
  presa a rótulos que o autor digita na mão;
- e o modelo pede um pedido de confiança frágil ao convidado: *"guarda esse link
  secreto e não passa pra ninguém"*.

Não reabrir sem fato novo. O caminho é OAuth — que os clientes suportam **out of
the box** e que, com um provedor gerenciado, custa menos do que parece.

## 1. A experiência (o que o amigo vive)

```
  landing (raspador-eventos.vercel.app)
      │  "Conectar ao Claude" → copia a URL do conector, abre a tela certa
      ▼
  Claude → Configurações → Conectores → Adicionar conector personalizado
      │  cola  https://raspador-eventos.vercel.app/mcp    (URL PÚBLICA)
      ▼
  Claude bate no /mcp → recebe 401 → descobre o servidor de autorização
      ▼
  abre a tela de LOGIN + CONSENTIMENTO (do AuthKit, com a nossa marca)
      │  "Eventos de Brasília quer acessar sua conta" → [Permitir]
      ▼
  conectado. "o que tem de pagode esse fim de semana?"
```

**O gesto de colar a URL permanece** — não existe deep link oficial que instale
um connector a partir do nosso site (anexo §3). O que a landing faz é levar a
pessoa até o lugar certo com a URL já copiada. O "Connect" de um clique só existe
para quem está no **Connector Directory** da Anthropic, que passa por revisão
deles: é um objetivo legítimo depois que isto estiver no ar e sendo usado — não
agora.

**O que muda de fato:** a URL deixa de ser a senha. Ela é **pública** — pode ir
para um story do Instagram, um grupo de WhatsApp, o README do repo. Quem controla
o acesso é o login.

## 2. Arquitetura — nós somos Resource Server, não Authorization Server

```
   Claude (cliente OAuth)
      │  1. GET /mcp  →  401 + WWW-Authenticate: resource_metadata="…"
      │  2. lê /.well-known/oauth-protected-resource  → descobre o issuer
      │  3. registra-se sozinho (DCR) e manda o usuário logar
      ▼
   ┌──────────────────────┐        ┌─────────────────────────────────┐
   │  AuthKit (WorkOS)    │        │  MCP remoto (Vercel)            │
   │  AUTHORIZATION SERVER│◄──────►│  RESOURCE SERVER                │
   │  login + consent     │  JWKS  │  /mcp  → valida o JWT (TokenVe- │
   │  DCR, PKCE, tokens   │        │  rifier) → tools → consulta.py  │
   └──────────────────────┘        └────────────────┬────────────────┘
                                                    ▼  SELECT
                                            Neon (Postgres)
```

**Não guardamos senha, não emitimos token, não escrevemos fluxo OAuth.** O
provedor faz login (Google/e-mail), tela de consentimento, registro dinâmico do
cliente, PKCE e refresh. Nós só **verificamos o JWT** que chega — e o SDK do MCP
já traz o resto (§4).

## 3. Decisões (e as alternativas rejeitadas)

| Decisão | Por quê | Rejeitado |
|---|---|---|
| **OAuth (DCR)** em vez de credencial na URL | É o que o Claude suporta out of the box; dá **identidade real** (quem logou), revogação por pessoa, expiração e refresh; e libera a URL para ser divulgada | **Token na URL** (§0). **`static_headers`**: credencial de *organização*, cadastrada por admin — não existe para amigo com conta pessoal. **`none`** (aberto): sem identidade, sem teto crível, o Neon free na chuva |
| **Provedor gerenciado: WorkOS AuthKit** | DCR liga com um toggle no dashboard, tem doc de MCP própria, e o free tier (1M MAU) é ordens de grandeza maior que qualquer coisa que a gente sonhe | **Escrever nosso Authorization Server**: DCR + PKCE + `/authorize` + `/token` + rotação de refresh é código de segurança — dias de trabalho e dívida permanente numa PoC. **Auth0**: fica como fallback (recomenda CIMD, setup com mais peças). **Stytch**: comprada pela Twilio, risco de foco |
| **Verificar o JWT localmente** (JWKS cacheado) | ~ms, sem round-trip a cada request; o handshake não toca o banco nem o IdP | Introspecção remota por request: +1 chamada de rede no caminho quente, e o timeout de 10 s do Claude é implacável |
| **Aberto a quem logar** (não allowlist) | O objetivo é distribuir; exigir aprovação manual mata o "posta o link e a galera usa". O controle é *reativo*: teto por usuário + bloqueio | Allowlist de e-mails: vira fila de aprovação e trabalho manual do autor a cada amigo |
| **Registrar chamada de tool com identidade** (`usuarios` + `acessos`) | Fecha o critério da Fase 1 com dado real e responde a pergunta de produto mais valiosa: **o que as pessoas perguntam** | Log só de request HTTP: mostra tráfego, não intenção |

**O que NÃO muda:** transporte (streamable HTTP stateless), host (Vercel), base
(Neon), tools, `consulta.py`. A abertura é uma casca de autorização em volta do
que já existe e funciona.

## 4. O que o SDK já dá de graça — e o que sobra pra gente

O `mcp` instalado (**1.10.1**) já suporta o modo Resource Server. Ligando
`FastMCP(auth=AuthSettings(...), token_verifier=...)`, ele sozinho:

- instala o `BearerAuthBackend` (extrai e valida o token de todo request);
- **exige** auth e responde **`401` com `WWW-Authenticate: Bearer
  resource_metadata="…"`** — exatamente o que o Claude precisa para descobrir o
  issuer (anexo §4);
- serve **`/.well-known/oauth-protected-resource`** (RFC 9728) com `resource`,
  `authorization_servers` e `scopes_supported`;
- expõe o token autenticado às tools via `get_access_token()` (contextvar).

**Sobra escrever um `TokenVerifier`** (`src/acesso.py`, ~40 linhas): baixa o JWKS
do AuthKit (cacheado em memória), valida assinatura/`iss`/`aud`/`exp` com
`PyJWT[crypto]` e devolve um `AccessToken` estendido com `sub` e `email` (o
`AccessToken` do SDK não tem esses campos — subclasse pydantic).

> ⚠️ **Armadilha a validar no smoke (custa horas se passar batido).** O SDK monta
> o header do 401 como `resource_server_url + "/.well-known/oauth-protected-
> resource"`, mas registra a **rota** na raiz do app. Com
> `resource_server_url = https://host/mcp` (que é o que o Claude exige: o
> `resource` precisa bater com a URL digitada), o header aponta para
> `https://host/mcp/.well-known/oauth-protected-resource` — path que o app **não
> serve** por padrão. Solução: montar um **alias** dessa rota (Starlette `Route`
> extra ou rewrite no `vercel.json`) e conferir com `curl` que os dois caminhos
> devolvem o mesmo JSON, com `resource` idêntico à URL do connector.

## 5. Schema — duas tabelas novas (`sql/schema.sql`)

```sql
-- Quem conectou o MCP remoto. Preenchida no PRIMEIRO acesso autenticado
-- (upsert pelo sub do IdP); nao ha cadastro nosso — o login e do AuthKit.
CREATE TABLE IF NOT EXISTS usuarios (
    sub        TEXT PRIMARY KEY,  -- id estavel do usuario no AuthKit (claim `sub` do JWT)
    email      TEXT,              -- claim `email` — e o que torna o registro legivel p/ o autor
    nome       TEXT,
    criado_em  TEXT NOT NULL,     -- ISO UTC "+00:00" — primeiro acesso
    visto_em   TEXT,              -- ISO UTC — ultimo acesso
    bloqueado  INTEGER NOT NULL DEFAULT 0  -- 1 = corta o acesso (abuso); reativo, sem allowlist previa
);

-- Instrumentacao (PRD §10): uma linha por chamada de tool. Registra a INTENCAO
-- (os argumentos, incl. o texto buscado) — e o insumo de produto da abertura,
-- nao so contagem de trafego.
CREATE TABLE IF NOT EXISTS acessos (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sub        TEXT,              -- usuarios.sub; NULL = chamada local (stdio, sem auth)
    em         TEXT NOT NULL,     -- ISO UTC "+00:00"
    tool       TEXT NOT NULL,     -- buscar_eventos | detalhar_evento | buscar_filmes | sessoes_filme | data_atual
    args       TEXT,              -- JSON dos argumentos da chamada
    resultados INTEGER,           -- nº de itens devolvidos (quando a tool devolve lista)
    ms         INTEGER,
    erro       TEXT
);
CREATE INDEX IF NOT EXISTS idx_acessos_sub_em ON acessos(sub, em);
```

**Ponto de atenção — `usuarios` é o primeiro dado NÃO derivável de raspagem.** A
convenção de base descartável (`DROP SCHEMA public CASCADE` + re-raspar) apagaria
o histórico de quem usou. Diferente da v1, isso **não quebra o acesso de
ninguém** (a identidade vive no AuthKit; a tabela se repovoa sozinha no próximo
acesso) — perde-se só o histórico. Mitigação barata: `SELECT` de `usuarios`/
`acessos` para CSV antes de dropar, quando o histórico importar. Registrar o
aviso no cabeçalho do `sql/schema.sql` e no CLAUDE.md.

## 6. Identidade, teto e registro — nas tools (`src/mcp_server.py`)

Um decorator `@registrado` nas 5 tools. **O verificador de token não toca o
banco** (só valida o JWT) — quem escreve é o decorator, de modo que o handshake
do Claude não gera escrita nem custo:

1. `get_access_token()` → `sub`/`email` (no stdio devolve `None`: chamada local,
   sem sub, sem teto — o `test_mcp_server.py` continua passando).
2. **Upsert em `usuarios`** (cria no primeiro acesso, atualiza `visto_em`).
3. **Bloqueado?** → devolve `{"erro": "Acesso suspenso."}`.
4. **Fora do teto?** (`COUNT` de `acessos` do `sub` na última hora ≥
   `LIMITE_HORA`, constante começando em **120**) → devolve
   `{"erro": "Limite de consultas por hora atingido. Tente daqui a pouco."}` —
   erro de dado, não exceção de transporte, para o agente saber explicar.
5. Executa, cronometra e grava em `acessos` (tool, args, nº de resultados, ms,
   erro).

O teto existe porque a URL agora é **pública**: ele é a defesa do free tier do
Neon/Vercel contra uso anômalo, e o bloqueio é a defesa contra abuso deliberado.

Como `psycopg` é síncrono e as tools rodam em contexto async, as escritas vão
para `anyio.to_thread.run_sync` (não travar o event loop).

Consequência assumida: as tools deixam de ser 100% finas (ganham um decorator).
O preço fica confinado ao decorator — `consulta.py` segue intocada.

## 7. Landing page — `public/index.html` + rotas

Página estática (sem framework, sem build), servida pela mesma Vercel:

- o que é, em uma frase, e três exemplos de pergunta;
- botão **"Copiar URL do conector"** + link para a tela do Claude
  (`claude.ai/settings/connectors?modal=add-custom-connector` — atalho, não
  contrato: o passo a passo textual funciona sozinho se ele mudar);
- passo a passo com prints, incluindo o aviso de que **no plano grátis do Claude
  cabe 1 connector personalizado**;
- nota de privacidade (§8), curta e honesta;
- nota de que é uma PoC de fim de semana, cobrindo **só Brasília**.

**`vercel.json` muda:** hoje reescreve **todas** as rotas para `api/index.py`.
Passa a rotear `/mcp` e `/.well-known/*` para a função Python (mais o alias da
armadilha do §4) e servir o estático na raiz.

## 8. Privacidade — agora há PII de verdade

Com OAuth, passamos a guardar **e-mail e nome** (vêm do login) — dado pessoal, ao
contrário da v1. O que registramos: quem (sub/e-mail), quando, qual tool e os
**argumentos** (inclui o texto buscado: "pagode", "funk"). Não guardamos IP,
user-agent nem senha (nunca vemos a senha: o login é do AuthKit).

A landing **diz isso em uma linha**, e a tela de consentimento do provedor já
deixa explícito o que está sendo autorizado. Instrumentação é honesta ou não é.

## 9. Fora de escopo (deliberado)

- **Connector Directory da Anthropic** (o "Connect" de um clique) — pleitear
  depois que estiver no ar, estável e com uso real. Exige revisão deles.
- **ChatGPT e Gemini** — mesma URL funciona no ChatGPT (Plus + Developer Mode);
  o Gemini consumidor não fala MCP. Não construir nada específico (anexo §2).
- **Escopos granulares, multi-tenant, papéis** — um escopo de leitura basta.
- **Allowlist / fila de aprovação** — controle é reativo (teto + bloqueio).
- **Cara própria de produto** (site de busca para humanos) e **Porta B** (páginas
  com JSON-LD) — Fase 2. A landing aqui é uma página de instalação, não um produto.
- **Painel de uso** — SQL no DBeaver e um `--relatorio` bastam.

## 10. Operação

- **Envs novas** (Vercel + `.env` local): `AUTHKIT_ISSUER` (ex.:
  `https://<slug>.authkit.app`), `MCP_RESOURCE_URL` (a URL pública do connector,
  `https://raspador-eventos.vercel.app/mcp`). `MCP_SEGREDO` **morre** — a URL
  passa a ser pública; remover do código e das settings.
- **Dependência nova:** `PyJWT[crypto]` (validação da assinatura via JWKS).
  `httpx` já vem com o SDK `mcp`.
- **Setup no WorkOS:** criar app, ligar **DCR** (Connect → Configuration),
  registrar o redirect `https://claude.ai/api/mcp/auth_callback`, escolher os
  escopos padrão, e configurar a marca da tela de consentimento (é ela que o
  amigo vê).
- **O connector do autor troca:** a URL secreta atual deixa de existir; o autor
  reconecta na URL pública e loga como qualquer um (bom: ele passa pelo fluxo que
  vai vender).
- **Pré-requisito de produto, não técnico — NI-10 (GitHub Actions).** Hoje a base
  só atualiza quando o autor roda `atualizar.py` na mão. Para o autor, uma base de
  três dias atrás é um incômodo conhecido; para um amigo, é **resposta errada com
  cara de certa** — o jeito mais rápido de queimar a confiança no primeiro uso.
  Subir o cron **antes** de divulgar. Não bloqueia esta implementação; bloqueia a
  divulgação.
- **Limites do free tier a vigiar:** Vercel Hobby é licenciado para uso **não
  comercial** (ok para PoC); Neon free tem compute hours limitadas e hiberna (a
  primeira consulta da noite continua lenta — PRD §8); AuthKit dá 1M MAU. Com
  `acessos` no ar, dá para medir o consumo real antes de precisar decidir
  qualquer coisa sobre plano pago.

## 11. Plano de teste / critério de aceite

`tests/test_acesso.py` (novo, contra `eventos_teste`; usa `httpx.ASGITransport`
sobre o app — `httpx` já é dependência do SDK `mcp`):

- **sem token** → `401` **com** `WWW-Authenticate: Bearer resource_metadata="…"`
  (é o handshake inteiro: se isso quebra, o Claude nunca acha o login);
- `GET /.well-known/oauth-protected-resource` (e o **alias** do §4) → JSON com
  `resource` **idêntico** à URL do connector e o issuer certo;
- **token forjado / expirado / de outro issuer** → `401`;
- **token válido** (assinado por um par de chaves de teste, com o JWKS mockado) →
  tools respondem;
- usuário novo aparece em `usuarios`; cada tool chamada aparece em `acessos` com
  tool, args e nº de resultados;
- **bloqueado** → `{"erro": ...}`; **teto** estourado → `{"erro": ...}` e **sem**
  consulta à base;
- stdio (`test_mcp_server.py`, existente) continua passando — sem auth, sem teto.

**Smoke em produção** (é o teste que importa): plugar
`https://raspador-eventos.vercel.app/mcp` como connector no Claude **de uma conta
que não é a do autor**, passar pelo login e pelo consentimento, e fazer uma
pergunta real. Conferir `usuarios`/`acessos`.

**Critério de aceite (Fase 1, PRD §6):** ≥ 2 conhecidos conectados por conta
própria, e a tabela `acessos` mostrando consultas **deles**, em dias diferentes,
sem o autor ter puxado. Uso comprovado por registro — não por "achei que usaram".

## 12. Ordem de implementação

1. **Spike de 1h no WorkOS** (antes de escrever código de produção): criar o app,
   ligar DCR, e conectar um MCP de brinquedo no Claude para ver a tela de
   consentimento aparecer. É o risco de integração inteiro — se o AuthKit não
   fechar o fluxo com o Claude, o fallback é o Auth0 e o resto da spec não muda.
2. `sql/schema.sql`: `usuarios` + `acessos`.
3. `src/acesso.py`: `TokenVerifier` (JWKS + PyJWT), `AccessToken` estendido com
   `sub`/`email`, upsert de usuário, teto, bloqueio, registro.
4. `src/mcp_server.py`: `AuthSettings` + `token_verifier` no `FastMCP`, decorator
   `@registrado` nas 5 tools; `api/index.py` monta o alias do well-known (§4).
   `MCP_SEGREDO` sai.
5. `tests/test_acesso.py` + os testes existentes.
6. `public/index.html` (landing) + `vercel.json` (rotas) + `vercel --prod` + smoke
   com conta de terceiro.
7. Docs: `CLAUDE.md` (arquitetura, envs, comandos), `docs/TESTE_MCP.md` (o fluxo
   do convidado, com prints), backlog (NI-11 sai; nota reforçando NI-10 como
   pré-requisito da divulgação), PRD §4 (registrar que a Porta A ganhou login).
