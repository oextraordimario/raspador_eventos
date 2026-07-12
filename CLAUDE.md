# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

PoC que raspa eventos de cinco plataformas (Sympla, Ingresse, Shotgun, Zig,
Ticket and Go), unifica num
schema único em **Postgres gerenciado (Neon)** e expõe a base para agentes de IA via
MCP, para responder perguntas em linguagem natural (ex.: *"quais festas de pagode
neste fim de semana?"*). Desde a Fase 0b o read-path vive na nuvem: a raspagem roda
local (na mão) e grava direto na base remota; a consulta funciona com o PC desligado.

**Escopo deliberadamente estreito:** só **Brasília (DF)**. O código hoje cobre
**festas/baladas/shows** (vida noturna) e **cinema** (a grade de 8 cinemas-alvo via
API da Ingresso.com — NI-07, domínio próprio `filmes`/`sessoes`, fora de `eventos`).
O roadmap do MVP prevê ainda o **Instagram** como fonte de contexto/enriquecimento —
**planejado, não implementado** (ver `docs/PRD_MVP.md`). Outras cidades seguem fora.
Ao mexer nos scrapers ou nas consultas, não generalize além do escopo do PRD sem
pedido explícito.

A hipótese de risco central do produto é a **raspagem** (se ela funciona, o resto é
considerado tranquilo). Prioridade nº 1 do usuário: validar/manter a raspagem.

## Comandos

```bash
# Setup
pip install -r requirements.txt
python -m playwright install chromium          # necessário só p/ o Shotgun
# .env na raiz (gitignorado) com EVENTOS_DB_URL e EVENTOS_DB_URL_TESTE
# (connection strings dos bancos eventos/eventos_teste no Neon)

# Atualização sob demanda — o comando da Fase 0 (raspa as 5 fontes → marca sumidos
# → descreve/precifica → raspa a grade de cinema → deriva (inclui filmes/sessoes)
# → enriquece com ruído/dedupe → FTS → relatório de saúde com comparação vs.
# rodada anterior → grava a rodada em `execucoes`). Rodar antes de usar o agente.
python src/atualizar.py
python src/atualizar.py --sem-shotgun           # pula Shotgun (lento, usa navegador)
python src/atualizar.py --sem-cinema            # pula a grade de cinema
python src/atualizar.py --precificar-tudo       # tickets de TODOS os futuros (default: janela de 30 dias)
python src/atualizar.py --so-derivar            # não raspa; re-deriva do payload bruto + regras + FTS
python src/atualizar.py --so-enriquecer         # não raspa; só reaplica regras + FTS

# Demo da PoC (raspa e roda consultas de exemplo; mantida como registro)
python src/demo.py
python src/demo.py --sem-shotgun
python src/demo.py --so-consultar               # só consulta o que já está na base

# Camada de consulta isolada (roda exemplos de buscar_eventos)
python src/consulta.py

# MCP server (normalmente quem executa é o cliente de IA; assim é só p/ depurar)
python src/mcp_server.py                        # stdio (clientes locais)
python src/mcp_server.py --http                 # MCP remoto local (exige MCP_SEGREDO; porta da env PORT)

# Deploy do MCP remoto em produção (Vercel, projeto raspador-eventos; as envs
# EVENTOS_DB_URL — URL pooled do Neon — e MCP_SEGREDO vivem nas settings de lá)
vercel --prod

# Testes de fumaça (scripts executáveis, sem framework). Os 3 primeiros usam o
# banco descartável eventos_teste no Neon (EVENTOS_DB_URL_TESTE; recriam o
# schema do zero — ver tests/base_teste.py), então exigem internet.
python tests/test_enriquecer.py                 # ruído + dedupe + efeito na consulta
python tests/test_bronze.py                     # camadas Bronze/Prata (eventos_raw, lotes, derivação, detalhar_evento) e guarda anti-Bileto
python tests/test_observabilidade.py            # execucoes + sumido + janela do precificar
python tests/test_cinema.py                     # domínio cinema: cinema_raw + snapshot, filmes/sessoes, buscar_filmes/sessoes_filme
python tests/test_zig_ticketandgo.py            # fontes novas (NI-22): normalização, filtro DF textual, lotes c/ taxa fracionária
python tests/test_mcp_server.py                 # age como cliente MCP real (stdio); exige base já populada

# Redescobrir a API interna do Sympla, se ela mudar
python src/scrapers/discover_sympla.py          # gera capturas_sympla.json (na raiz)
```

Não há suíte de testes formal nem linter — os testes são scripts executáveis em
`tests/`. O interpretador usado no ambiente é `C:/Python313/python.exe`
(referenciado em `.mcp.json`).

## Arquitetura

Duas frentes acopladas por uma base única — **Postgres no Neon** desde a Fase 0b
(driver psycopg 3; antes era SQLite local). A connection string vem de
`EVENTOS_DB_URL` (variável de ambiente, com fallback no `.env` da raiz — resolvido
por `store.env_var`). Testes usam o banco `eventos_teste` via `EVENTOS_DB_URL_TESTE`.
Spec da migração: `docs/specs/20260711_consulta-na-nuvem/`.

Todo o código Python vive em `src/`:

```
src/
  store.py  consulta.py  enriquecer.py  derivar.py  tempo.py  # núcleo (imports irmãos)
  atualizar.py  mcp_server.py  demo.py            # entrypoints
  scrapers/
    sympla.py  ingresse.py  shotgun.py  zig.py  ticketandgo.py  cinema.py  discover_sympla.py
api/           # entrypoint serverless do MCP remoto (Vercel): index.py (deps: pyproject.toml da raiz)
sql/           # schema.sql + reconstruir_fts.sql (fonte única do DDL, roda no DBeaver/psql)
docs/          # PRD, backlogs/, specs/ (specs técnicas de implementação)
tests/         # scripts executáveis + base_teste.py (redireciona p/ eventos_teste)
```

O DDL não fica embutido em string Python: mora em `sql/schema.sql` e é **carregado**
por `store.conectar()`. Ao mudar o schema, edite o `.sql` (não o `store.py`). O SQL
dinâmico (upsert, updates de derivação/enriquecimento) segue no código, porque não
roda standalone.

Rodar entrypoints a partir da **raiz** do repo (ex.: `python src/demo.py`); o
`sys.path[0]` vira `src/`, então `import store`/`import consulta` resolvem como irmãos,
e `demo.py` importa os scrapers via `from scrapers import ...`.

**Frente A — Raspagem.** Um módulo por fonte em `src/scrapers/`, cada um com uma função
`raspar(...)` que devolve uma lista de dicts já normalizados para o schema unificado:
- `src/scrapers/sympla.py` — API JSON interna de descoberta (`discovery-bff/search`), sem
  navegador. Filtra por tema `99` ("Festas e Shows"). Paginado. A **descrição e a
  categoria real** vêm de outro BFF (`event-page.svc.sympla.com.br/.../event/{id}`,
  id numérico do FIM da URL pública — difere do id do catálogo), via
  `raspar_descricao(...)`, chamada pelo passo incremental "descrever" do `atualizar.py`.
- `src/scrapers/ingresse.py` — BFF FastAPI `api-site.ingresse.com/events/search`, sem auth,
  schema em `/openapi.json`. Catálogo de Brasília é pequeno. Descrição via
  `GET /events/{slug}` (`raspar_descricao`), também no passo "descrever".
- `src/scrapers/shotgun.py` — **exige Playwright**: o site bloqueia HTTP puro (429) e renderiza
  via RSC. Pagina a listagem da cidade (`/pt/cities/<slug>?page=N`) até esgotar,
  extrai slugs `/events/<slug>` (links **relativos** — a regex tem que casar path
  relativo) e lê o JSON-LD (`MusicEvent`) de cada evento — incluindo os campos ricos
  (`description`/`performer`/`organizer`/`offers` → descricao/atracoes/organizador/
  preco_min), que vêm de graça na mesma página.
- `src/scrapers/zig.py` — API do SuperTicket (`ticket-api.superticket.com.br/events`,
  plataforma que a Zig incorporou), sem auth/navegador. **Sem filtro server-side de
  estado**: pagina o catálogo nacional (~6 páginas) e filtra
  `event_location.state == "DF"` do lado de cá. Descrição via `GET /events/{slug}`
  (`raspar_descricao`), no passo "descrever". **Preço fica fora** (endpoint de
  tickets responde vazio — spec NI-22 §3); preco_min NULL = "não informou".
- `src/scrapers/ticketandgo.py` — `POST production-api-v1-service.ticketandgo.com.br/
  eventos/pesquisa` com `{"pesquisa": ""}` devolve o **catálogo inteiro já com a
  descrição** (sem passo "descrever"). cidade/estado vêm NULOS: o filtro DF é
  **textual** sobre `local`/`endereco_completo` (`_do_df`: Brasília / `\bDF\b` /
  CEP 70–73) e cidade/estado são rotulados, como no Shotgun. Datas locais separadas
  (`inicio` + `hora_incio`, typo da fonte) compostas com `-03:00`. Lotes via
  `GET /eventos/{slug}` (`raspar_tickets`) no passo "precificar";
  `taxa_conveniencia` é FRAÇÃO (0.1 = 10%) somada ao valor na derivação.
- `src/scrapers/cinema.py` — **contrato próprio** (devolve a grade bruta, não lista de
  eventos): API de conteúdo da Ingresso.com (`api-content.ingresso.com/v0/sessions/
  city/12/theater/{id}?date=...`, sem auth/navegador) para os **8 cinemas-alvo**
  (dict `CINEMAS`: theaterId → apelido canônico). 404 = dia sem sessão (não é
  erro). Raspa 8 dias corridos (a programação vira na quinta). Fallbacks por rede
  mapeados em `spikes/cinema/README.md`. Spec: `docs/specs/20260711_raspagem-cinema/`.
- Cada scraper preenche `ULTIMA_RASPAGEM` (módulo) com `coletados`/`total_site`
  ao fim de `raspar()` — é daí que o `atualizar.py` mede cobertura (no cinema,
  coletados = cinemas que responderam ≥ 1 dia).
- `src/scrapers/discover_sympla.py` — ferramenta de reconhecimento, não faz parte do pipeline:
  intercepta XHR/fetch num navegador para achar a API interna quando um site muda.

**Frente B — Consulta por IA.**
- `src/store.py` — aplica o schema (`sql/schema.sql`) + `upsert_eventos` (chave
  `<fonte>:<id_nativo>` evita colisão; **normaliza as datas na escrita** — ver
  Convenções) + busca textual por coluna `busca tsvector` (config `pt`: unaccent +
  stemming português). Depois de raspar, chame `reconstruir_fts(con)` (roda
  `sql/reconstruir_fts.sql`) para recalcular a coluna. A chave reservada `_raw` do
  dict normalizado (payload bruto da fonte) vai para a **camada Bronze**
  (`eventos_raw`, PK `evento_id+origem` — Sympla tem 2 payloads por evento:
  catálogo e detalhe), junto com `gravar_raw(...)` para o payload do "descrever".
- `src/derivar.py` — derivação a seco (a "camada Prata"): (re)calcula colunas de
  `eventos` e a tabela `lotes` a partir de `eventos_raw`, sem rede. Os lotes de
  ingresso viram linhas de `lotes` (nome CRU da fonte, `preco` = total a pagar com
  taxa, `taxa`, `gratis`, `esgotado`); `preco_min`/`tem_gratis`/`esgotado` de
  `eventos` são agregações deles — `preco_min` é o menor lote **PAGO** (cortesia não
  mascara o preço real, NI-18) e `tem_gratis` marca lote grátis não esgotado.
  `cancelado`, `bairro` e `popularidade` seguem derivados direto do payload. Campo
  novo do bruto = função aqui + `--so-derivar`, **sem re-raspar**. Idempotente como
  o enriquecer. Os payloads de tickets (Sympla/Ingresse/Ticket and Go) vêm do passo "precificar"
  do `atualizar.py` — **não incremental** (preço/lote é volátil; refeito a cada
  rodada, mas só para eventos na **janela de 30 dias** — `--precificar-tudo` cobre
  todos os futuros), e no Sympla só para eventos com descrição validada (âncora da
  guarda NI-17 — o endpoint de tickets não devolve nome). Specs:
  `docs/specs/20260710_camada-bronze/`, `20260710_camada-prata/` e
  `20260710_lotes-ingressos/`. **Domínio cinema**: `aplicar_cinema(con)` reconstrói
  `filmes`/`sessoes` do zero a partir de `cinema_raw` (SNAPSHOT: sessão de cinema
  não tem id estável entre semanas, então a grade nova substitui a anterior —
  sem upsert, sem dedupe, sem `sumido`; o id do FILME é estável e é a PK).
- `src/enriquecer.py` — enriquecimento v1 (regras, sem LLM): marca ruído
  (anúncio/curso, por palavra-chave no nome) e agrupa duplicatas cross-fonte
  (mesmo dia + nome/local similares). **Marca, não apaga** — quem esconde é a
  consulta. `aplicar(con)` é idempotente: reseta e recalcula tudo, então mudar
  regra não exige re-raspar (`python src/atualizar.py --so-enriquecer`).
- `src/consulta.py` — `buscar_eventos(texto, cidade, data_inicio, data_fim, limite,
  incluir_ruido)`, todos os args opcionais, retorno JSON-serializável. Por padrão
  esconde ruído, não-canônicos de dedupe, **cancelados** e **sumidos** (evento
  futuro que não reapareceu no catálogo da fonte); esgotado NÃO some (é
  resposta útil). O canônico traz `outras_urls` (links do mesmo evento nas outras
  plataformas). `detalhar_evento(url)` aprofunda UM evento: descrição INTEIRA (a
  busca corta em `DESCRICAO_MAX`) + lista de lotes — a condição do lote ("CORTESIA
  FEMININA ATÉ 00H") fica no nome cru, de propósito: quem interpreta é o agente,
  não regex. Esta é a camada canônica de consulta.
  No cinema, `buscar_filmes(texto, data_inicio, data_fim, cinema, limite)` agrega
  por filme (sessões futuras por padrão) e `sessoes_filme(filme, ...)` detalha
  horários/salas/tipos/preço de UM filme (lookup por id ou título parcial).
- `src/mcp_server.py` — FastMCP expondo tools finas que delegam para
  `consulta.py`: `buscar_eventos` (listar), `detalhar_evento` (aprofundar um
  evento: descrição completa + lotes), `buscar_filmes`/`sessoes_filme` (cinema)
  e `data_atual` (data/hora UTC + janela do
  fim de semana, para o agente montar filtros "hoje"/"neste fim de semana").
  Transporte stdio por default; `--http` sobe o **MCP remoto** (streamable HTTP
  stateless, rota sob prefixo secreto `MCP_SEGREDO`, porta da env `PORT`) — é o
  connector do celular na Fase 0b (NI-20).

Fluxo: `scraper.raspar()` → `store.upsert_eventos()` (grava também o bruto na Bronze) →
marcar sumidos (evento futuro que não reapareceu no catálogo de fonte raspada SEM
erro → `sumido=1`; a consulta esconde) → descrever (busca incremental da descrição
p/ Sympla/Ingresse/Zig; upsert usa COALESCE p/ nunca zerá-la) → precificar (tickets/
lotes p/ a Bronze, refeito a cada rodada na janela de 30 dias) → cinema
(`cinema.raspar()` → `store.gravar_cinema_raw()`, snapshot com poda de dias
passados) → `derivar.aplicar()` + `derivar.aplicar_cinema()` → `enriquecer.aplicar()` →
`store.reconstruir_fts()` (eventos E filmes) → relatório (compara coleta com a
rodada anterior e ALERTA queda > 50% — detector de scraper quebrado) →
`store.registrar_execucao()`
(tabela `execucoes`: uma linha por rodada, com erros POR evento) →
`consulta.buscar_eventos()` →
tool MCP → agente de IA. `atualizar.py` orquestra tudo isso sob demanda;
`mcp_server.py` é o ponto de entrada em uso real; `demo.py` é a demo da PoC.
O FTS indexa nome/categoria/atracoes/**descricao** — "eletrônica" acha evento sem o
gênero no nome (em filmes: titulo/generos).

## Convenções e armadilhas

- **Schema unificado é o contrato.** Todo scraper normaliza para os campos definidos
  em `sql/schema.sql` (`id`, `fonte`, `nome`, `start_date`, `cidade`, `url`, etc.) antes
  de gravar. Ao adicionar uma fonte, siga o mesmo `_normalizar(...)` → dict.
- **Datas em formatos mistos.** Sympla/Ingresse usam `+00:00`, Shotgun usa `.000Z`,
  Zig usa `.000-03:00` e o Ticket and Go manda data e hora locais SEPARADAS e sem
  fuso (o scraper compõe com `-03:00`). O parse mora em UM lugar: `src/tempo.py` (`instante` → datetime UTC; `norm_ts` →
  texto ISO comparável). Desde a Fase 0b quem resolve é a **escrita**: o
  `upsert_eventos` normaliza `start_date`/`end_date`/`raspado_em` com `norm_ts`
  (invariante do schema: ISO UTC `+00:00`), e a `consulta.py` normaliza os
  parâmetros — a comparação no SQL é lexical e segura. Não grave data nessas
  colunas fora do upsert sem normalizar, nem reimplemente parse local.
- **`raspado_em` é a âncora do `sumido`:** só o upsert do catálogo o atualiza
  (descrever/precificar mexem em outras colunas). Não atualize `raspado_em` fora
  do upsert, ou a detecção de evento sumido quebra.
- **Cidade no Shotgun** vem como bairro em `addressLocality`; a cidade é rotulada
  pelo parâmetro de busca (`cidade_label`), não pelo dado bruto. No **Ticket and
  Go**, cidade/estado vêm NULOS da fonte e também são rotulados (pelo filtro
  textual `_do_df`).
- **URLs do Bileto (`bileto.sympla.com.br`) não passam pelo "descrever":** o id no
  fim delas é de OUTRO namespace, e o BFF de página devolveria um evento alheio sem
  erro HTTP (bug NI-17, achado no spike da Bronze). Além do filtro de URL, o
  `_descrever` valida o nome devolvido (`_mesmo_nome`) antes de gravar — não remova
  essa guarda.
- **Ruído conhecido na base:** o filtro `themes=99` do Sympla deixa passar
  anúncios/cursos — tratados pelo filtro v1 de `enriquecer.py` (na dúvida, a regra
  NÃO marca: falso positivo esconde festa real; termos já testados e descartados em
  `docs/backlogs/rejeitado.yaml`). `end_date` às vezes vem inconsistente na origem
  (filtre por `start_date`).
- **Schema mudou? A base é descartável.** `conectar()` só roda `IF NOT EXISTS`;
  não há migração. Ao alterar `sql/schema.sql`, rode `DROP SCHEMA public CASCADE;
  CREATE SCHEMA public;` no banco `eventos` (DBeaver/psql) e re-raspe
  (`atualizar.py` detecta base antiga e instrui isso).
- **MCP / FastMCP:** retorno `list` vira `structuredContent["result"]` + um content
  block por item; retorno `dict` vira content block único. `tests/test_mcp_server.py`
  lida com os dois formatos.
- Config de MCP em `.mcp.json` (Claude Code detecta sozinho). Setup dos 3 clientes
  (Claude Code, Claude Desktop, Codex) em `docs/TESTE_MCP.md`.

## Estratégia de commit

O usuário commita **em partes lógicas** e prefere disparar ele mesmo ("segue").
Não faça commit sem pedido. Mensagens em português.

## Documentos de referência

- `docs/PRD_MVP.md` — **fonte da verdade atual**: visão do MVP, escopo, moat,
  modelo de distribuição (híbrido/invisível-first), roadmap por fases (0/1/2).
- `docs/PRD_POC.md` — registro histórico da prova de conceito (validação da raspagem).
- `docs/backlogs/` — backlog em dois YAMLs filtráveis: `nao-iniciado.yaml` (itens
  abertos, com campo `status`: pendente/não-iniciado) e `rejeitado.yaml` (testado e
  descartado). Implementado de verdade sai da lista (git/spec registram). Substitui o
  antigo `docs/PROXIMOS_PASSOS.md` (hoje só um ponteiro).
- `docs/specs/` — specs técnicas de implementação (o "como" de cada item, uma pasta
  datada por spec com `spec.md`). Ver `docs/specs/README.md`.
- `docs/TESTE_MCP.md` — como plugar o MCP server nos clientes de IA.
