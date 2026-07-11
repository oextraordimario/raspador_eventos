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

## 5. MCP remoto (Fase 0b) — connector no celular

O mesmo server sobe em HTTP, protegido por um prefixo de rota secreto
(`MCP_SEGREDO`); a URL completa é o segredo — qualquer rota fora dela dá 404.

Testar local:

```bash
# PowerShell:  $env:MCP_SEGREDO="um-segredo-longo"; $env:PORT="8765"
python src/mcp_server.py --http
# URL do connector: http://localhost:8765/<segredo>/mcp
```

Em produção o server roda na **Vercel** (projeto `raspador-eventos`, plano
hobby): o entrypoint é `api/index.py` (app ASGI do FastMCP; o `vercel.json`
manda todas as rotas pra ele) e as envs `EVENTOS_DB_URL` (URL **pooled** do
Neon) e `MCP_SEGREDO` ficam nas settings do projeto na Vercel. Deploy:
`vercel --prod` na raiz do repo (CLI logado). A URL base é
`https://raspador-eventos.vercel.app` — o segredo NÃO fica em arquivo nenhum
do repo (só na env da Vercel).

No app do Claude (celular ou web): **Configurações → Conectores → Adicionar
conector personalizado**, colando `https://<host>/<segredo>/mcp`. Não divulgar
a URL — auth de verdade é a Fase 1 (NI-11). Spec:
`docs/specs/20260711_consulta-na-nuvem/`.

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
