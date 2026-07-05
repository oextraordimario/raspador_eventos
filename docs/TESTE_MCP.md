# Como testar a Frente B (MCP) com um agente de IA

O `mcp_server.py` expõe a base de eventos como duas tools, via MCP (transporte
stdio) — compatível com **Claude Code**, **Claude Desktop** e **Codex**.

Tools disponíveis:
- **`buscar_eventos(texto, cidade, data_inicio, data_fim, limite)`** — busca
  festas/baladas na base unificada (Sympla + Ingresse + Shotgun).
- **`data_atual()`** — data/hora atual e a janela do fim de semana (ajuda o agente
  a montar filtros como "hoje" ou "neste fim de semana").

---

## 1. Pré-requisitos (uma vez)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # se ainda não fez
python demo.py                          # popula a base eventos.db
```

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
C:\Users\mgbju\AppData\Roaming\Claude\claude_desktop_config.json
```

Adicione o bloco `mcpServers`:

```json
{
  "mcpServers": {
    "eventos-brasilia": {
      "command": "C:/Python313/python.exe",
      "args": ["C:/Users/mgbju/Documents/GitHub/raspador_eventos/mcp_server.py"]
    }
  }
}
```

Salve e **reinicie o Claude Desktop**. O server aparece no ícone de ferramentas
(🔨) da caixa de mensagem.

---

## 4. Codex

Edite (crie se não existir) `C:\Users\mgbju\.codex\config.toml` e adicione:

```toml
[mcp_servers.eventos-brasilia]
command = "C:/Python313/python.exe"
args = ["C:/Users/mgbju/Documents/GitHub/raspador_eventos/mcp_server.py"]
```

Salve e reinicie o Codex.

---

## 5. Perguntas para testar

Com o server conectado em qualquer um dos clientes, pergunte em linguagem natural:

- "Quais festas de pagode vão ter em Brasília?"
- "Tem alguma balada de funk neste fim de semana em Brasília?"
- "O que tem pra fazer hoje à noite em Brasília?"
- "Me lista os próximos 5 shows em Brasília com o link pra comprar."

O agente deve chamar `data_atual` (quando o período for relativo) e
`buscar_eventos`, e responder com eventos reais da base, com data, local e URL.

---

## 6. Se algo falhar

- **Server não conecta / "module not found: mcp":** o cliente está usando outro
  Python. Confirme que `C:/Python313/python.exe` é o que tem as dependências
  (`pip install -r requirements.txt` nesse interpretador).
- **Respostas vazias:** a base pode estar vazia — rode `python demo.py`.
- **Datas erradas ("fim de semana"):** o agente deve chamar `data_atual` primeiro;
  se não chamar, peça explicitamente "considerando a data de hoje".
