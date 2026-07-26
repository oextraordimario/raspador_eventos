# Como testar a Frente B (MCP) com um agente de IA

O `src/mcp_server.py` expõe a base de eventos (Postgres no Neon desde a Fase 0b)
como tools, em dois transportes: **stdio** (clientes locais: Claude Code, Claude
Desktop, Codex) e **streamable HTTP** (`--http`, o MCP remoto usado como
connector no celular — seção 5).

Tools disponíveis:
- **`buscar_eventos(texto, cidade, data_inicio, data_fim, limite)`** — busca
  festas/baladas na base unificada (Sympla + Ingresse + Shotgun).
- **`detalhar_evento(url)`** — aprofunda UM evento: descrição completa + lotes.
- **`data_atual()`** — data/hora atual e a janela do fim de semana (ajuda o agente
  a montar filtros como "hoje" ou "neste fim de semana").

---

## 1. Pré-requisitos (uma vez)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # se ainda não fez
# .env na raiz com EVENTOS_DB_URL (connection string do banco eventos no Neon)
python src/atualizar.py                 # popula a base remota
```

> O `store.py` resolve `EVENTOS_DB_URL` do ambiente ou do `.env` da raiz do
> repo — os clientes stdio não precisam de configuração de env extra.

Verificação rápida de que o server está saudável (opcional):

```bash
python tests/test_mcp_server.py
```

Deve terminar com `OK — MCP server responde como cliente real espera.`

> Os caminhos nas configs abaixo apontam para
> `C:/Python313/python.exe` e para este repositório. Se o Python ou a pasta do
> projeto estiverem em outro lugar, ajuste os caminhos.

---

## 2. Claude Code

Já existe um **`.mcp.json`** na raiz do projeto. Basta abrir o Claude Code dentro
da pasta do projeto — ele detecta o server `eventos-brasilia` e pede aprovação
para habilitá-lo. Confirme e pronto.

Conferir: `/mcp` deve listar `eventos-brasilia` como conectado.

---

## 3. Claude Desktop

Edite (crie se não existir):

```
C:\Users\<seu-usuario>\AppData\Roaming\Claude\claude_desktop_config.json
```

Adicione o bloco `mcpServers`:

```json
{
  "mcpServers": {
    "eventos-brasilia": {
      "command": "C:/Python313/python.exe",
      "args": ["C:/Users/<seu-usuario>/Documents/GitHub/raspador_eventos/src/mcp_server.py"]
    }
  }
}
```

Salve e **reinicie o Claude Desktop**. O server aparece no ícone de ferramentas
(🔨) da caixa de mensagem.

---

## 4. Codex

Edite (crie se não existir) `C:\Users\<seu-usuario>\.codex\config.toml` e adicione:

```toml
[mcp_servers.eventos-brasilia]
command = "C:/Python313/python.exe"
args = ["C:/Users/<seu-usuario>/Documents/GitHub/raspador_eventos/src/mcp_server.py"]
```

Salve e reinicie o Codex.

---

## 5. MCP remoto — connector no celular

**URL do connector: `https://raspador-eventos.vercel.app/mcp`** — pública, e
pode ser divulgada: quem protege é o OAuth, não o sigilo do endereço.

No app do Claude (celular ou web): **Configurações → Conectores → Adicionar
conector personalizado**, colando a URL acima. O app abre a tela de login do
AuthKit sozinho; depois de entrar, as tools aparecem. Nada de chave, token ou
segredo para colar — nenhum dos dois lados guarda credencial nossa.

Em Claude Code: `claude mcp add -t http raspador https://raspador-eventos.vercel.app/mcp`
e depois `/mcp` para autenticar.

### Como funciona

O server é **resource server**, nunca authorization server (`src/auth.py`).
O cliente faz o caminho inteiro sem configuração:

1. chama `/mcp` sem token → **401** com `WWW-Authenticate` apontando para
   `/.well-known/oauth-protected-resource/mcp`;
2. lê ali o issuer do **AuthKit (WorkOS)** e descobre os endpoints dele;
3. registra-se sozinho (DCR/CIMD, habilitados no AuthKit) e faz o code flow;
4. volta com `Authorization: Bearer <jwt>`, que verificamos contra o JWKS.

Conferir sem cliente nenhum:

```bash
curl https://raspador-eventos.vercel.app/.well-known/oauth-protected-resource/mcp
curl -i -X POST https://raspador-eventos.vercel.app/mcp   # deve dar 401
```

Testar local (o mesmo modo de produção, com o issuer de verdade):

```bash
AUTHKIT_ISSUER=https://prompt-color-48-staging.authkit.app \
  MCP_RECURSO=http://localhost:8765/mcp PORT=8765 python src/mcp_server.py --http
```

### Produção

Roda na **Vercel** (projeto `raspador-eventos`, plano hobby), entrypoint
`api/index.py`. Envs nas settings de lá: `EVENTOS_DB_URL` (URL **pooled** do
Neon), `AUTHKIT_ISSUER` e `MCP_RECURSO`. Deploy: `vercel --prod` na raiz.

> **Ambiente do AuthKit:** hoje aponta para o **Staging** do WorkOS
> (`prompt-color-48-staging.authkit.app`). O Production já está configurado
> igual (`pleasant-globe-47.authkit.app`) e a troca é só a env
> `AUTHKIT_ISSUER` — falta ativar Production no painel do WorkOS. Ao trocar,
> todo mundo re-autentica: as identidades (`sub`) são por ambiente.

**Rollback:** apagar `AUTHKIT_ISSUER` + `MCP_RECURSO` e redeployar volta ao modo
anterior, sob o prefixo secreto `MCP_SEGREDO` (a rewrite `/:segredo/mcp` segue
no `vercel.json` justamente para isso).

Specs: `docs/specs/20260711_consulta-na-nuvem/`, `20260726_abrir-ao-publico/`.

---

## 6. Perguntas para testar

Com o server conectado em qualquer um dos clientes, pergunte em linguagem natural:

- "Quais festas de pagode vão ter em Brasília?"
- "Tem alguma balada de funk neste fim de semana em Brasília?"
- "O que tem pra fazer hoje à noite em Brasília?"
- "Me lista os próximos 5 shows em Brasília com o link pra comprar."

O agente deve chamar `data_atual` (quando o período for relativo) e
`buscar_eventos`, e responder com eventos reais da base, com data, local e URL.

---

## 7. Se algo falhar

- **Server não conecta / "module not found: mcp":** o cliente está usando outro
  Python. Confirme que `C:/Python313/python.exe` é o que tem as dependências
  (`pip install -r requirements.txt` nesse interpretador).
- **"EVENTOS_DB_URL nao definida":** falta o `.env` na raiz (ou a variável de
  ambiente) com a connection string do Neon.
- **Respostas vazias:** a base pode estar vazia — rode `python src/atualizar.py`.
- **Primeira resposta lenta da noite:** o Neon free hiberna após inatividade;
  o wake custa alguns segundos e só afeta a primeira consulta.
- **Datas erradas ("fim de semana"):** o agente deve chamar `data_atual` primeiro;
  se não chamar, peça explicitamente "considerando a data de hoje".
- **Connector remoto dá 401 mesmo depois de logar:** o motivo real fica no log
  da função na Vercel (`[auth] token recusado: ...`) — o cliente só mostra
  "unauthorized". Quase sempre é o `aud`: o token vale para o resource indicator
  que o cliente pediu, e ele precisa bater com `MCP_RECURSO` **e** estar
  registrado no AuthKit (Connect → Configuration → Resource Indicators).
