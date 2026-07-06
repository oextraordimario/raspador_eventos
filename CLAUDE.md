# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

PoC que raspa eventos de três plataformas (Sympla, Ingresse, Shotgun), unifica num
schema único em SQLite e expõe a base para agentes de IA via MCP, para responder
perguntas em linguagem natural (ex.: *"quais festas de pagode neste fim de semana?"*).

**Escopo deliberadamente estreito:** só **Brasília (DF)** e só **festas/baladas**
(vida noturna). Outras cidades e tipos de evento estão fora por ora. Ao mexer nos
scrapers ou nas consultas, não generalize além disso sem pedido explícito.

A hipótese de risco central do produto é a **raspagem** (se ela funciona, o resto é
considerado tranquilo). Prioridade nº 1 do usuário: validar/manter a raspagem.

## Comandos

```bash
# Setup
pip install -r requirements.txt
python -m playwright install chromium          # necessário só p/ o Shotgun

# Pipeline ponta a ponta (raspa as 3 fontes → grava eventos.db → roda consultas)
python demo.py
python demo.py --sem-shotgun                    # pula Shotgun (lento, usa navegador)
python demo.py --so-consultar                   # só consulta o que já está na base

# Camada de consulta isolada (roda exemplos de buscar_eventos)
python consulta.py

# MCP server (normalmente quem executa é o cliente de IA; assim é só p/ depurar)
python mcp_server.py

# Teste de fumaça do MCP (age como cliente MCP real; exige base já populada)
python tests/test_mcp_server.py

# Redescobrir a API interna do Sympla, se ela mudar
python discover_sympla.py                       # gera capturas_sympla.json
```

Não há suíte de testes formal nem linter — `tests/test_mcp_server.py` é um único
smoke test executável. O interpretador usado no ambiente é `C:/Python313/python.exe`
(referenciado em `.mcp.json`).

## Arquitetura

Duas frentes acopladas por uma base SQLite única (`eventos.db`, gitignorada):

**Frente A — Raspagem.** Um módulo por fonte, cada um com uma função `raspar(...)`
que devolve uma lista de dicts já normalizados para o schema unificado:
- `sympla.py` — API JSON interna de descoberta (`discovery-bff/search`), sem
  navegador. Filtra por tema `99` ("Festas e Shows"). Paginado.
- `ingresse.py` — BFF FastAPI `api-site.ingresse.com/events/search`, sem auth,
  schema em `/openapi.json`. Catálogo de Brasília é pequeno.
- `shotgun.py` — **exige Playwright**: o site bloqueia HTTP puro (429) e renderiza
  via RSC. Abre a página da cidade num Chromium headless, extrai slugs
  `/events/<slug>` (links **relativos** — a regex tem que casar path relativo) e lê
  o JSON-LD (`MusicEvent`) de cada evento.
- `discover_sympla.py` — ferramenta de reconhecimento, não faz parte do pipeline:
  intercepta XHR/fetch num navegador para achar a API interna quando um site muda.

**Frente B — Consulta por IA.**
- `store.py` — schema SQLite unificado + `upsert_eventos` (chave `<fonte>:<id_nativo>`
  evita colisão) + índice FTS5 (`eventos_fts`) para busca textual. Depois de raspar,
  chame `reconstruir_fts(con)` para reindexar.
- `consulta.py` — `buscar_eventos(texto, cidade, data_inicio, data_fim, limite)`,
  todos os args opcionais, retorno JSON-serializável. Esta é a camada canônica de
  consulta.
- `mcp_server.py` — FastMCP stdio expondo duas tools finas que delegam para
  `consulta.py`: `buscar_eventos` e `data_atual` (data/hora UTC + janela do fim de
  semana, para o agente montar filtros "hoje"/"neste fim de semana").

Fluxo: `scraper.raspar()` → `store.upsert_eventos()` → `store.reconstruir_fts()` →
`consulta.buscar_eventos()` → tool MCP → agente de IA. `demo.py` orquestra a parte
de raspagem+consulta; `mcp_server.py` é o ponto de entrada em uso real.

## Convenções e armadilhas

- **Schema unificado é o contrato.** Todo scraper normaliza para os campos de
  `store.py` (`id`, `fonte`, `nome`, `start_date`, `cidade`, `url`, etc.) antes de
  gravar. Ao adicionar uma fonte, siga o mesmo `_normalizar(...)` → dict.
- **Datas em formatos mistos.** Sympla/Ingresse usam `+00:00`, Shotgun usa `.000Z`.
  Comparação lexical de strings falha entre eles. `consulta.py` normaliza toda data
  via `_norm_ts` (registrada como função SQL `norm_ts`) antes de comparar/ordenar —
  não volte a comparar `start_date` como string crua.
- **Cidade no Shotgun** vem como bairro em `addressLocality`; a cidade é rotulada
  pelo parâmetro de busca (`cidade_label`), não pelo dado bruto.
- **Ruído conhecido na base:** o filtro `themes=99` do Sympla ainda deixa passar
  anúncios/cursos; `end_date` às vezes vem inconsistente na origem (filtre por
  `start_date`). Ver `docs/PROXIMOS_PASSOS.md`.
- **MCP / FastMCP:** retorno `list` vira `structuredContent["result"]` + um content
  block por item; retorno `dict` vira content block único. `tests/test_mcp_server.py`
  lida com os dois formatos.
- Config de MCP em `.mcp.json` (Claude Code detecta sozinho). Setup dos 3 clientes
  (Claude Code, Claude Desktop, Codex) em `docs/TESTE_MCP.md`.

## Estratégia de commit

O usuário commita **em partes lógicas** e prefere disparar ele mesmo ("segue").
Não faça commit sem pedido. Mensagens em português.

## Documentos de referência

- `docs/PRD.md` — visão, escopo, hipótese de risco, plano das frentes.
- `docs/PROXIMOS_PASSOS.md` — backlog priorizado (qualidade das respostas do agente,
  classificação de gênero, cobertura/frescor, migração p/ Postgres local).
- `docs/TESTE_MCP.md` — como plugar o MCP server nos clientes de IA.
