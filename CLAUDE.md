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
**festas/baladas/shows** (vida noturna), **cinema** (a grade de 8 cinemas-alvo via
API da Ingresso.com — NI-07, domínio próprio `filmes`/`sessoes`, fora de `eventos`)
e o **Instagram** como fonte de contexto E de eventos (casas que só divulgam no
Insta — spec `docs/specs/20260723_instagram-como-fonte/`): posts/stories da
watchlist (`dados/perfis_instagram.yaml`) via API paga do Monid, flyer lido por
visão (`claude -p`), post com data vira evento `fonte='instagram'`. Outras cidades
seguem fora. Ao mexer nos scrapers ou nas consultas, não generalize além do escopo
do PRD sem pedido explícito.

A hipótese de risco central do produto é a **raspagem** (se ela funciona, o resto é
considerado tranquilo). Prioridade nº 1 do usuário: validar/manter a raspagem.

## Comandos

```bash
# Setup
pip install -r requirements.txt
python -m playwright install chromium          # necessário só p/ o Shotgun
# .env na raiz (gitignorado) com EVENTOS_DB_URL e EVENTOS_DB_URL_TESTE
# (connection strings dos bancos eventos/eventos_teste no Neon)
# Instagram (opcional): npm i -g @monid-ai/cli && monid keys add -k <key> -l main
# (conta em app.monid.ai; a chave fica no config do monid, NÃO no repo) +
# CLI `claude` logado na assinatura (extração do flyer por visão)

# Atualização sob demanda — o comando da Fase 0 (raspa as 5 fontes → marca sumidos
# → descreve/precifica → raspa a grade de cinema → deriva (inclui filmes/sessoes)
# → enriquece com ruído/dedupe → FTS → relatório de saúde com comparação vs.
# rodada anterior → grava a rodada em `execucoes`). Rodar antes de usar o agente.
python src/atualizar.py
python src/atualizar.py --sem-shotgun           # pula Shotgun (lento, usa navegador)
python src/atualizar.py --sem-cinema            # pula a grade de cinema
python src/atualizar.py --sem-instagram         # pula o Instagram (Monid + claude -p)
python src/atualizar.py --sem-extracao-flyer    # Instagram só até a Bronze, sem a visão
python src/atualizar.py --so-instagram          # só a fila de extração (rodada curta)
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
# MCP remoto local. Com OAuth (o modo de produção): serve /mcp + a rota de
# metadados, e recusa chamada sem token do AuthKit.
AUTHKIT_ISSUER=https://prompt-color-48-staging.authkit.app \
  MCP_RECURSO=http://localhost:8765/mcp PORT=8765 python src/mcp_server.py --http
python src/mcp_server.py --http                 # sem as duas envs: modo antigo, exige MCP_SEGREDO

# Site público (NI-28) — front Next.js + API de leitura em Python
npm install                                     # 1ª vez
python api/dados.py 8000                        # API de leitura (lê consulta.py)
API_INTERNA=http://localhost:8000/api/dados npm run dev    # front em :1007
# (a porta 1007 está fixada nos scripts do package.json; `npx next dev` sem o
#  script cairia na 3000. A Vercel não usa esses scripts — lá é build+serverless.)
npx next build                                  # build de produção

# Deploy em produção (Vercel, projeto raspador-eventos). As envs vivem nas
# settings de lá: EVENTOS_DB_URL (URL pooled do Neon), AUTHKIT_ISSUER +
# MCP_RECURSO (OAuth do MCP) e MCP_SEGREDO (resquício do modo anterior).
vercel --prod

# Testes de fumaça (scripts executáveis, sem framework). Os 3 primeiros usam o
# banco descartável eventos_teste no Neon (EVENTOS_DB_URL_TESTE; recriam o
# schema do zero — ver tests/base_teste.py), então exigem internet.
python tests/test_enriquecer.py                 # ruído + dedupe + efeito na consulta
python tests/test_bronze.py                     # camadas Bronze/Prata (eventos_raw, lotes, derivação, detalhar_evento) e guarda anti-Bileto
python tests/test_observabilidade.py            # execucoes + sumido + janela do precificar
python tests/test_cinema.py                     # domínio cinema: cinema_raw + snapshot, filmes/sessoes, buscar_filmes/sessoes_filme
python tests/test_zig_ticketandgo.py            # fontes novas (NI-22): normalização, filtro DF textual, lotes c/ taxa fracionária
python tests/test_instagram.py                  # fonte Instagram: guarda da derivação, data do flyer, conciliação via dedupe, sumido
python tests/test_api_dados.py                  # API de leitura do site: filtros da camada canônica + postura (trecho, organizador oculto)
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
  auth.py                                         # verifica o token OAuth do MCP remoto
  atualizar.py  mcp_server.py  demo.py            # entrypoints
  scrapers/
    sympla.py  ingresse.py  shotgun.py  zig.py  ticketandgo.py  cinema.py  instagram.py  discover_sympla.py
api/           # funções serverless (Vercel; deps: pyproject.toml da raiz)
  index.py     #   MCP remoto (ASGI do FastMCP)
  dados.py     #   API de leitura do site — traduz querystring p/ consulta.py
app/  lib/     # front Next.js (App Router) do site público — NA RAIZ, não em web/
.github/workflows/raspar.yml   # cron diário da raspagem (NI-10)
sql/           # schema.sql + reconstruir_fts.sql (fonte única do DDL, roda no DBeaver/psql)
dados/         # dado curado à mão, versionado (perfis_instagram.yaml — a watchlist NI-24)
docs/          # PRD, backlogs/, specs/ (specs técnicas de implementação)
tests/         # scripts executáveis + base_teste.py (redireciona p/ eventos_teste)
```

**O front mora na RAIZ (`app/`, `lib/`, `package.json`), não numa subpasta.** É o
arranjo que a Vercel suporta para framework + funções Python no mesmo projeto:
`api/*.py` convivem com o build do Next. Com o front em subpasta seria preciso
configurar Root Directory e "include files outside root" no dashboard —
configuração invisível no repo, que quebra em silêncio.

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
  (`raspar_descricao`), no passo "descrever". **Preço vem do `__NEXT_DATA__` da
  página pública** (NI-23: o SSR embute `pageProps.tickets` — value + fee separada;
  o endpoint JSON de tickets responde vazio sem códigos do front e o `json_ld` da
  página tem preços errados, não usar), no passo "precificar" com guarda de nome.
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
- `src/scrapers/instagram.py` — **contrato próprio** (devolve payloads brutos por perfil,
  não lista de eventos): posts + stories ativos dos perfis da watchlist
  (`dados/perfis_instagram.yaml`) via CLI do **Monid** (`monid`, subprocess —
  revenda dos endpoints TikHub; chave no config do monid, nunca no repo; ~$0,006
  por perfil/rodada, o 1º custo recorrente aceito do projeto). Também abriga
  `extrair(...)` (legenda + TODAS as páginas do carrossel numa chamada de visão →
  JSON com **LISTA de eventos** — carrossel-agenda vira um item por evento, v1.1
  §8; via `claude -p` headless com Sonnet na ASSINATURA — o env do subprocesso
  remove `ANTHROPIC_API_KEY`, que teria precedência sobre o login) e
  `montar_start_date(...)` (data "25/07" do flyer + `taken_at` do post → próxima
  ocorrência no fuso de Brasília; ano explícito no passado = retrospectiva, e ano
  inferido a mais de 270 dias não vira evento). Quem transforma post em evento
  (`fonte='instagram'`) é `derivar.aplicar_instagram`. Spec:
  `docs/specs/20260723_instagram-como-fonte/`.
- Cada scraper preenche `ULTIMA_RASPAGEM` (módulo) com `coletados`/`total_site`
  ao fim de `raspar()` — é daí que o `atualizar.py` mede cobertura (no cinema,
  coletados = cinemas que responderam ≥ 1 dia; no Instagram, perfis cujos posts
  responderam).
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
  **Instagram**: `aplicar_instagram(con)` reconstrói os eventos `fonte='instagram'`
  do zero a partir de `instagram_raw` (payload do post + extração, ambos na
  Bronze — a "Prata" do Instagram é a própria `eventos`). A extração é uma LISTA
  (v1.1): post comum = 1 item → `instagram:<code>`; carrossel-agenda = N itens →
  `instagram:<code>:<n>` com URL `?img_index=<n>` (n = posição na lista, estável
  — itens reprovados não renumeram); formato antigo (objeto com `e_evento`) é
  lido por adaptador, sem re-extrair. Guarda POR ITEM: confiança ALTA + nome +
  data resolvida (errar p/ o lado de NÃO criar). Preço do flyer vira lote
  sintético ("entrada (do flyer)") p/ as agregações funcionarem sem caso
  especial. Roda DEPOIS de `aplicar()` (que trunca `lotes`).
- `src/enriquecer.py` — enriquecimento v1 (regras, sem LLM): marca ruído
  (anúncio/curso, por palavra-chave no nome) e agrupa duplicatas — cross-fonte
  (mesmo dia + nome/local similares) e **intra-fonte** (NI-01, regra mais
  apertada: mesmo dia + mesmo local OBRIGATÓRIO + nome ≥ `SIM_NOME_INTRA`).
  O "mesmo dia" é o dia LOCAL de Brasília (bucket UTC separava 20h de 22h da
  mesma noite). **Marca, não apaga** — quem esconde é a consulta. `aplicar(con)`
  é idempotente: reseta e recalcula tudo, então mudar regra não exige re-raspar
  (`python src/atualizar.py --so-enriquecer`).
  O dedupe também é a **conciliação Instagram ↔ plataforma** (NI-25) e
  **agenda ↔ post do dia** (v1.1 §8.4): o post que virou evento agrupa pelo
  mesmo mecanismo, com os `local_aliases` da watchlist canonizando o local
  ("Culto" ↔ "Culto Rock Bar") via parâmetro `aliases_local`; `instagram` é o
  último em `_PREF_FONTE` (quem vende o ingresso é o canônico; o post entra em
  `outras_urls`) e `preco_min` conta na completude (o post individual, com
  preço do flyer, vence a linha da agenda).
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
- `api/dados.py` — **API de leitura do site** (NI-28). Ponte entre o front (JS) e
  a camada canônica (Python): traduz querystring em chamadas de `consulta.py` e
  devolve o JSON delas. **Sem lógica própria** — as duas únicas transformações
  são de POSTURA e vêm da spec: `descricao` sai em TRECHO (600 chars; a tool MCP
  segue integral, porque serve agente em contexto privado, não página indexada) e
  `organizador` NUNCA é exposto (às vezes é pessoa física → LGPD). Rotas sob
  `/api/dados/*`. Roda local com `python api/dados.py`.
- `app/` + `lib/` — **site público** (Next.js App Router). Os filtros vivem na
  URL (`?periodo=&texto=&gratis=`), não em estado de cliente: funciona sem JS,
  cada combinação é endereço compartilhável e o SSR entrega HTML pronto — que é
  o que a Fase 2 precisa que o buscador leia. Visual pelo **ZeroUm Design
  System**; nome do produto isolado em `lib/config.js` (é PROVISÓRIO, não
  espalhar). Sem imagens de evento no v1 (decisão da spec). `app/sitemap.js`,
  `app/robots.js` e `app/llms.txt/route.js` são a Porta B da Fase 2, e cada
  página de evento carrega JSON-LD `schema.org/Event`.
- `src/mcp_server.py` — FastMCP expondo tools finas que delegam para
  `consulta.py`: `buscar_eventos` (listar), `detalhar_evento` (aprofundar um
  evento: descrição completa + lotes), `buscar_filmes`/`sessoes_filme` (cinema)
  e `data_atual` (data/hora UTC + janela do
  fim de semana, para o agente montar filtros "hoje"/"neste fim de semana").
  Transporte stdio por default; `--http` sobe o **MCP remoto** (streamable HTTP
  stateless, porta da env `PORT`) — é o connector do celular (NI-20).
- `src/auth.py` — **OAuth do MCP remoto** (NI-11). Este servidor é *resource
  server*: quem emite token é o **AuthKit (WorkOS)**, e aqui só se verifica o
  JWT contra o JWKS do issuer. O cliente descobre tudo sozinho — leva 401 com
  `WWW-Authenticate`, lê `/.well-known/oauth-protected-resource/mcp`,
  registra-se via DCR/CIMD e volta com Bearer. Ligado por **env, não por
  flag**: `AUTHKIT_ISSUER` + `MCP_RECURSO` presentes = com auth em `/mcp`;
  ausentes = modo antigo sob o prefixo secreto `MCP_SEGREDO` (que é o rollback,
  sem tocar em código). O caminho da rota SAI de `MCP_RECURSO`, para o metadado
  anunciado nunca divergir da rota servida. `mcp>=1.28` é piso duro: é dela que
  vêm `AccessToken.claims`/`.subject` e a rota RFC 9728 correta. Com token
  válido, `_identidade()` passa a preencher `usuarios`/`acessos` sozinha.

Fluxo: `scraper.raspar()` → `store.upsert_eventos()` (grava também o bruto na Bronze) →
marcar sumidos (evento futuro que não reapareceu no catálogo de fonte raspada SEM
erro → `sumido=1`; a consulta esconde) → descrever (busca incremental da descrição
p/ Sympla/Ingresse/Zig; upsert usa COALESCE p/ nunca zerá-la) → precificar (tickets/
lotes p/ a Bronze, refeito a cada rodada na janela de 30 dias) → cinema
(`cinema.raspar()` → `store.gravar_cinema_raw()`, snapshot com poda de dias
passados) → instagram (`instagram.raspar()` → `store.gravar_instagram_raw()`,
Bronze acumulativa + extração do flyer via `claude -p` só p/ post NOVO ≤ 60 dias;
falha re-tenta na próxima rodada) → `derivar.aplicar()` +
`derivar.aplicar_instagram()` + `derivar.aplicar_cinema()` →
`enriquecer.aplicar(aliases_local=...)` →
`store.reconstruir_fts()` (eventos E filmes) → relatório (compara coleta com a
rodada anterior e ALERTA queda > 50% — detector de scraper quebrado) →
`store.registrar_execucao()`
(tabela `execucoes`: uma linha por rodada, com erros POR evento) →
`consulta.buscar_eventos()` →
tool MCP → agente de IA. `atualizar.py` orquestra tudo isso sob demanda;
`mcp_server.py` é o ponto de entrada em uso real; `demo.py` é a demo da PoC.
O FTS indexa nome/categoria/atracoes/**descricao** + **local_nome/organizador**
(v1.1: "o que tem no Ordinário?" acha pela casa rotulada, mesmo com a legenda
dizendo só "Ordi") — "eletrônica" acha evento sem o gênero no nome (em filmes:
titulo/generos).

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
- **Instagram tem regras próprias:** (a) URL de mídia do CDN **expira em horas** —
  baixar na hora da ingestão (`midias/instagram/`, gitignorado), nunca gravar a
  URL na base; (b) a fonte fica **FORA** do `_marcar_sumidos` (guarda explícita:
  post que sai da 1ª página do perfil não significa cancelamento); (c) a
  watchlist é dado **curado à mão e versionado** (`dados/perfis_instagram.yaml`)
  — não mover para a base, que é descartável; (d) a extração do flyer roda na
  ASSINATURA (`claude -p`; o subprocess remove `ANTHROPIC_API_KEY` do env) e é
  incremental — nunca re-extrai shortcode que já tem origem `extracao` na Bronze.
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
- **Roteamento do `vercel.json` — as duas portas no mesmo domínio.** Até a Fase
  0b havia um catch-all mandando TODAS as rotas para `/api/index` (o MCP era a
  única porta). Com o site, ele saiu e sobraram rewrites explícitas; o Next fica
  com o resto (páginas, sitemap, robots, llms.txt). As do MCP são três:
  `/mcp` (o endpoint), `/.well-known/oauth-protected-resource/:recurso*` (a
  descoberta da RFC 9728 — **sem ela o cliente nunca sabe onde autenticar**, e o
  Next devolveria 404 no lugar) e `/:segredo/mcp`, que sobrou do modo anterior.
  Essa última **não** é o segredo literal: o prefixo vem da env `MCP_SEGREDO` e
  não pode ser versionado — o padrão casa qualquer primeiro segmento terminando
  em `/mcp`, e quem valida é o próprio app ASGI, que só monta a rota no path
  certo e devolve 404 no resto. Ela existe hoje só para o rollback do OAuth ser
  uma troca de env; quando o OAuth estiver rodado, pode sair.
  **Mexer aqui é o jeito mais fácil de derrubar o MCP sem perceber** — depois de
  alterar, confira que o connector ainda responde.
  O `vercel.json` **não aceita comentário** (nem `$comment`: o schema rejeita
  propriedade extra e o deploy falha), por isso esta explicação mora aqui.

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
- `docs/specs/20260726_abrir-ao-publico/` — spec **APROVADA e IMPLEMENTADA** em
  2026-07-26, exceto o OAuth do MCP (ver abaixo). É o plano de abrir o sistema a
  terceiros: LICENSE/README (NI-21), cron no GitHub Actions (NI-10), site público
  (NI-28), instrumentação (NI-11) e JSON-LD/sitemap (Fase 2). Anexos: `tos.md`
  (postura sobre Termos de Uso: **agregador com atribuição** — vale ler antes de
  mexer no que o site expõe) e `cron.md` (por que Actions, e o plano B em Cloud
  Run Jobs, com os gatilhos que o acionam).
- `docs/TESTE_MCP.md` — como plugar o MCP server nos clientes de IA.
