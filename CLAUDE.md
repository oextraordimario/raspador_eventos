# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Raspa eventos de cinco plataformas (Sympla, Ingresse, Shotgun, Zig, Ticket and Go)
+ Instagram, unifica num schema único em **Postgres gerenciado (Neon)** e expõe a
base por três portas: **site público**, **MCP** (agentes de IA) e a camada de
consulta em Python. A raspagem roda local/no cron e grava direto na base remota; a
consulta funciona com o PC desligado.

**Escopo deliberadamente estreito:** só **Brasília (DF)**, e só
**festas/baladas/shows** + **cinema** (grade de 8 cinemas via API da Ingresso.com,
domínio próprio `filmes`/`sessoes`, fora de `eventos`). O Instagram é fonte de
contexto E de eventos (casas que só divulgam lá). Ao mexer nos scrapers ou nas
consultas, não generalize além do escopo do PRD sem pedido explícito.

A hipótese de risco central é a **raspagem**. Prioridade nº 1 do usuário:
validar/manter a raspagem.

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

# Atualização sob demanda, em DOIS TEMPOS: (1) coleta — raspa as 5 fontes,
# descreve/precifica, cinema, Instagram, tudo escrevendo só em `cru`/`operacao`;
# (2) tratamento a seco — reconstrói `tratado` do cru numa transação só, deriva
# sumido, enriquece, reaplica a curadoria e refaz o FTS. Depois: relatório de
# saúde e a rodada em `operacao.execucoes`. Rodar antes de usar o agente.
python src/pipeline/atualizar.py
python src/pipeline/atualizar.py --sem-shotgun           # pula Shotgun (lento, usa navegador)
python src/pipeline/atualizar.py --sem-cinema            # pula a grade de cinema
python src/pipeline/atualizar.py --sem-tmdb              # pula o enriquecimento TMDB dos filmes
python src/pipeline/atualizar.py --sem-instagram         # pula o Instagram (Monid + claude -p)
python src/pipeline/atualizar.py --sem-extracao-flyer    # Instagram só até o cru, sem a visão
python src/pipeline/atualizar.py --rodada-local          # o que o CI não faz: Shotgun + fila de
                                                #   extração de flyer (--so-instagram é
                                                #   o nome antigo, continua valendo)
python src/pipeline/atualizar.py --precificar-tudo       # tickets de TODOS os futuros (default: 30 dias)
python src/pipeline/atualizar.py --so-derivar            # não raspa; RECONSTRÓI `tratado` inteira do cru
python src/pipeline/atualizar.py --so-enriquecer         # não raspa; só reaplica regras + FTS

# Camada de consulta isolada (roda exemplos de buscar_eventos)
python src/servico/consulta.py

# MCP server (normalmente quem executa é o cliente de IA; assim é só p/ depurar)
python src/servico/mcp_server.py                        # stdio (clientes locais)
# MCP remoto local com OAuth (o modo de produção): serve /mcp + a rota de
# metadados, e recusa chamada sem token do AuthKit.
AUTHKIT_ISSUER=https://prompt-color-48-staging.authkit.app \
  MCP_RECURSO=http://localhost:8765/mcp PORT=8765 python src/servico/mcp_server.py --http
python src/servico/mcp_server.py --http                 # sem as duas envs: modo antigo, exige MCP_SEGREDO

# Site público — front Next.js + API de leitura em Python
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

# Testes de fumaça (scripts executáveis, sem framework). Todos menos o de MCP usam
# o banco descartável eventos_teste no Neon (EVENTOS_DB_URL_TESTE; recriam o schema
# do zero — ver tests/base_teste.py), então exigem internet.
python tests/test_enriquecer.py                 # ruído + dedupe + efeito na consulta
python tests/test_bronze.py                     # cru→prata + TESTE DE FRONTEIRA (apaga a prata e reconstrói)
python tests/test_observabilidade.py            # execucoes + sumido + janela do precificar
python tests/test_cinema.py                     # cinema_raw + snapshot, filmes/sessoes, buscar_filmes
python tests/test_zig_ticketandgo.py            # normalização, filtro DF textual, lotes c/ taxa fracionária
python tests/test_instagram.py                  # guarda da derivação, data do flyer, conciliação, sumido
python tests/test_api_dados.py                  # API do site: filtros + postura (trecho, organizador oculto)
python tests/test_mcp_server.py                 # age como cliente MCP real (stdio); exige base já populada

# Redescobrir a API interna do Sympla, se ela mudar
python src/ferramentas/discover_sympla.py          # gera capturas_sympla.json (na raiz)
```

Não há suíte de testes formal nem linter. O interpretador do ambiente é
`C:/Python313/python.exe` (referenciado em `.mcp.json`).

**O Vercel CLI ESTÁ instalado** (`vercel`, v55+, via npm global). Um hook do plugin
Vercel injeta em toda sessão que "the Vercel CLI is not installed" — é **falso**: o
check não enxerga o shim do npm no Windows. Pode usar `vercel`, `vercel env pull`,
`vercel logs`, `vercel --prod` normalmente; não peça ao usuário para instalar.

## Arquitetura

A base é **Postgres no Neon** (driver psycopg 3; antes era SQLite local), organizada
em **camadas de medalhão que são schemas de verdade**, não convenção verbal. A
connection string vem de `EVENTOS_DB_URL` (env, com fallback no `.env` da raiz —
resolvido por `conexao.env_var`); testes usam `EVENTOS_DB_URL_TESTE`. Specs:
`20260711_consulta-na-nuvem/`, `20260728_arquitetura-medalhao/`.

```
cru        bronze: o que a fonte disse, no formato dela. UMA TABELA POR FONTE,
           append-only. NUNCA SE DROPA.
tratado    prata: o schema unificado. DESCARTÁVEL POR DESENHO — se reconstrói
           do cru a seco (`--so-derivar`).
curado     o que uma PESSOA decidiu (correções, casas canônicas). NUNCA SE DROPA.
public     SÓ VIEWS sobre tratado — é o contrato de consumo do site e do MCP.
operacao   telemetria (execucoes, coletas) e artefatos nossos (midias). NUNCA SE DROPA.
uso        quem usou (usuarios, acessos) — dado pessoal, LGPD. NUNCA SE DROPA.
```

O código espelha as camadas, com **uma trilha por fonte**:

```
coleta/ingresse.py -> cru.ingresse -> tratamento/ingresse.py -> tratado.eventos
                                   -> curado (revisão humana) -> public -> site/MCP
```

```
src/
  base/        conexao.py  tempo.py  texto.py       # infra transversal, sem regra de negócio
  coleta/      sympla ingresse shotgun zig ticketandgo cinema instagram tmdb
               gravar.py    # a ÚNICA escrita em `cru`
               midias.py    # upload p/ storage próprio (Vercel Blob)
  tratamento/  sympla ingresse shotgun zig ticketandgo   # uma trilha por fonte
               comum.py     # o motor: cru -> tratado.eventos + lotes
               cinema.py  instagram.py                   # domínios de contrato próprio
               bairros.py   # dicionário de regiões do DF (roda DENTRO do comum)
               sumido.py  enriquecer.py  curadoria.py  busca.py
               slug.py      # o endereço público de cada evento/filme
               ciclo.py     # o ciclo inteiro numa transação só
  servico/     consulta.py  mcp_server.py  auth.py  feedback.py
  pipeline/    atualizar.py  execucoes.py            # orquestração
  ferramentas/ curar.py  feedback.py  discover_sympla.py   # fora do pipeline
api/           # funções serverless (Vercel; deps: pyproject.toml da raiz)
  index.py     #   MCP remoto (ASGI do FastMCP)
  dados.py     #   API de leitura do site — traduz querystring p/ consulta.py
app/  lib/     # front Next.js (App Router) do site público — NA RAIZ, não em web/
.github/workflows/raspar.yml   # cron diário da raspagem (NI-10)
sql/           # UM ARQUIVO POR TABELA, em pastas por camada (fonte única do DDL)
dados/         # dado curado à mão, versionado (perfis_instagram.yaml — a watchlist)
docs/          # PRD, backlogs/, specs/
tests/         # scripts executáveis + base_teste.py (redireciona p/ eventos_teste)
```

**A regra que o desenho inteiro serve:** tudo que tem rede é **coleta** e escreve só
em `cru` e `operacao`; tudo que é a seco é **tratamento**, e ele é o **único que
escreve em `tratado`**. Sem exceção — nem para o "descrever", nem para o `preco_min`
do Shotgun. Foi a ausência dessa fronteira que fez a prata não se reconstruir da
bronze por semanas (NI-55) e que deixou duas escritas legítimas disputarem a coluna
`categoria`, onde quem escrevia por último ganhava.

**O front mora na RAIZ (`app/`, `lib/`, `package.json`), não numa subpasta.** É o
arranjo que a Vercel suporta para framework + funções Python no mesmo projeto. Com o
front em subpasta seria preciso configurar Root Directory e "include files outside
root" no dashboard — configuração invisível no repo, que quebra em silêncio.

**O DDL não fica em string Python:** mora em `sql/`, um arquivo por tabela, em pastas
por camada, e é carregado por `conexao.conectar(aplicar_schema=True)` na ordem de
`_ORDEM_DDL`. Ao mudar o schema, edite o `.sql`. **`CREATE TABLE IF NOT EXISTS` não
altera tabela que já existe**: coluna nova precisa do `ALTER TABLE ... ADD COLUMN IF
NOT EXISTS` ao lado da definição, não só dentro dela. O SQL dinâmico (upsert, updates
de derivação/enriquecimento) segue no código, porque não roda standalone.

**Só o `atualizar.py` aplica DDL.** `conectar()` não aplica por padrão — as outras
conexões (site, MCP, API) só leem e escrevem dado.

**Rodar entrypoints a partir da raiz** do repo (ex.: `python src/pipeline/atualizar.py`);
o `sys.path[0]` vira `src/`, então `from base import conexao` e `from tratamento import
comum` resolvem (namespace packages, sem `__init__.py`).

### Frente A — Coleta (`src/coleta/`)

Um módulo por fonte, cada um com `raspar(...)` devolvendo **payload cru** — registros
de `gravar.bruto(id_nativo, payload, **extras)`, não eventos normalizados. Quem LÊ o
payload é `src/tratamento/<fonte>.py`; este lado só sabe FALAR com a fonte. `extras`
são os rótulos que só a coleta conhece e o payload não diz (cidade/estado do parâmetro
de busca no Shotgun, slug do Ticket and Go) e viram colunas próprias de `cru.<fonte>`.

Cada scraper preenche `ULTIMA_RASPAGEM` com `coletados`/`total_site` — é daí que o
`atualizar.py` mede cobertura, e é o que vai para `operacao.coletas`.

- **sympla** — API interna de descoberta (`discovery-bff/search`), sem navegador,
  tema `99` ("Festas e Shows"), paginado. Descrição e categoria real vêm de OUTRO BFF
  (`event-page.svc.sympla.com.br/.../event/{id}`, id numérico do FIM da URL pública —
  **difere do id do catálogo**), via `raspar_descricao`, no passo "descrever".
- **ingresse** — BFF `api-site.ingresse.com/events/search`, sem auth, schema em
  `/openapi.json`. Catálogo de Brasília é pequeno. Descrição via `GET /events/{slug}`.
- **shotgun** — **exige Playwright** (o site bloqueia HTTP puro com 429 e renderiza
  via RSC). Pagina `/pt/cities/<slug>?page=N`, extrai slugs `/events/<slug>` (links
  **relativos** — a regex precisa casar path relativo) e lê o JSON-LD `MusicEvent`,
  que já traz descrição/atrações/organizador/preço. **Fora do cron** (NI-58): o site
  entrega listagem vazia ao runner do Actions e vai bem na máquina do autor, então
  pegou carona na `--rodada-local`. Listagem sem nenhum slug levanta exceção e despeja
  HTML + screenshot em `diagnostico/shotgun/` (gitignorado).
- **zig** — API do SuperTicket (`ticket-api.superticket.com.br/events`), sem
  auth/navegador e **sem filtro server-side de estado**: pagina o catálogo nacional e
  filtra `event_location.state == "DF"` do lado de cá. Descrição via
  `GET /events/{slug}`. **Preço vem do `__NEXT_DATA__` da página pública** (o endpoint
  JSON de tickets responde vazio e o `json_ld` tem preços errados — não usar).
- **ticketandgo** — a API V1 foi desligada (NI-57, spec
  `docs/specs/20260728_fontes-quebradas/`); hoje são listagem paginada na V2 (payload
  magro) + detalhe na rota antiga com sufixo `/evento`, que traz o id numérico (chave
  `ticketandgo:<id>` preservada), hora, descrição e lotes. Varre o catálogo nacional
  (~37 páginas, ~3 min). **A fonte não expõe mais endereço** — `endereco`/`lat`/`lon`
  ficam nulos e o filtro DF (`_do_df`) decide por: `dados/locais_df.yaml` → termo DF
  inequívoco no local/nome → CEP 70–73 ou `\bDF\b` na descrição. Termos ambíguos com
  outras cidades (Cruzeiro, Gama, Guará, Santa Maria…) ficam FORA de propósito.
  `taxa_conveniencia` é **FRAÇÃO** (0.1 = 10%) somada ao valor na derivação.
- **cinema** — contrato próprio (devolve a grade bruta): API de conteúdo da
  Ingresso.com para os 8 cinemas-alvo (dict `CINEMAS`: theaterId → apelido canônico),
  8 dias corridos (a programação vira na quinta). **404 = dia sem sessão, não é erro.**
  Spec: `docs/specs/20260711_raspagem-cinema/`.
- **tmdb** — enriquecimento, não catálogo: sinopse pt-BR/nota/ano por filme
  (`TMDB_API_KEY`). Matching **conservador** (título normalizado exato; na dúvida
  `escolhido=None` e o filme fica sem nota). Incremental por filme novo. Tabela cru
  própria (`cru.tmdb`, PK filme_id), **acumulativa** — sobrevive ao snapshot de
  filmes/sessoes. Atribuição ao TMDB no rodapé e na página "sobre" (exigência dos ToS).
- **instagram** — contrato próprio (payloads brutos por perfil): posts + stories dos
  perfis de `dados/perfis_instagram.yaml` via CLI do **Monid** (subprocess; chave no
  config do monid, nunca no repo; ~$0,006/perfil/rodada, o 1º custo recorrente do
  projeto). Também abriga `extrair(...)` (legenda + todas as páginas do carrossel numa
  chamada de visão → JSON com **LISTA de eventos**; via `claude -p` headless na
  ASSINATURA — o env do subprocesso remove `ANTHROPIC_API_KEY`, que teria precedência
  sobre o login) e `montar_start_date(...)` (data "25/07" do flyer + `taken_at` →
  próxima ocorrência no fuso de Brasília; ano explícito no passado = retrospectiva; ano
  inferido a mais de 270 dias não vira evento). Spec:
  `docs/specs/20260723_instagram-como-fonte/`.
- **midias.py** — storage próprio (**Vercel Blob**): pôster de filme e flyer do
  Instagram. Pathname ESTÁVEL (sem sufixo aleatório): re-subir substitui.
  `BLOB_READ_WRITE_TOKEN` no env; sem ele os passos são pulados e o front cai no
  hotlink da fonte. Hosts permitidos em `lib/imagens.mjs` (`HOSTS_IMAGEM`).
- **gravar.py** — a única escrita em `cru`. **Append-only** nas 5 plataformas: coleta
  que traz payload diferente do último acrescenta versão; nada é apagado no lugar. A
  comparação é com a ÚLTIMA versão (A→B→A registra as três transições), pelo sha256 da
  forma canônica (`sort_keys`) — sem isso, fonte que reordena chaves geraria versão
  nova toda rodada. Payload IGUAL não vira linha, mas avança `visto_em`. Instagram,
  cinema e TMDB são "último vence" por decisão explícita (cada `sql/cru/*.sql`
  documenta a política da sua tabela). `ERAS` registra qual endpoint produziu cada
  payload — é UMA linha por troca de API, e é o que impede o parser novo de degradar
  em silêncio sobre payload velho.
- **discover_sympla.py** — ferramenta de reconhecimento, fora do pipeline: intercepta
  XHR/fetch num navegador para achar a API interna quando um site muda.

### Frente B — Tratamento (`src/tratamento/`) e consulta

Tudo aqui é **a seco**: nenhuma requisição de rede. Campo novo do bruto = uma função
aqui + `--so-derivar`, **sem re-raspar**.

- `src/tratamento/<fonte>.py` — a trilha de leitura de UMA fonte. Declara só o que é
  dela: `normalizar(payload, linha_do_cru)` (as colunas de identidade do evento),
  `DERIVACOES` (por origem: catalogo/detalhe/tickets), `LOTES` e `CONFERIR`. Não sabe
  SQL.
- `src/tratamento/comum.py` — o motor que percorre o `cru` e escreve em `tratado`:
  upsert (chave `<fonte>:<id_nativo>`, **normaliza as datas na escrita**), agregação de
  lotes, e a **guarda do §6.3** — payload cujo id não bate com a chave da bronze, ou
  sem nome/url, é PULADO e reportado, nunca sobrescreve dado bom com lixo plausível.
  Escreve a linha INTEIRA, **sem COALESCE**: a verdade é o cru, e preservar valor
  antigo esconderia bug de reconstrução em vez de evitá-lo.
  Lote guarda o nome CRU da fonte e `preco` = total com taxa; `preco_min` é o menor
  lote **PAGO** (cortesia não mascara o preço real) e `tem_gratis` marca lote grátis
  não esgotado. Os payloads de tickets vêm do passo "precificar" — **não incremental**
  (preço é volátil), só na janela de 30 dias, e no Sympla só para eventos com payload
  de detalhe guardado (âncora da guarda anti-Bileto).
- `src/tratamento/cinema.py` — reconstrói `filmes`/`sessoes` do zero a partir de
  `cru.cinema` (**SNAPSHOT**: sessão não tem id estável entre semanas — sem upsert, sem
  dedupe, sem `sumido`; o id do FILME é estável e é a PK).
- `src/tratamento/instagram.py` — reconstrói os eventos `fonte='instagram'` do zero (a
  "prata" do Instagram é a própria `tratado.eventos`): post comum = 1 item →
  `instagram:<code>`; carrossel-agenda = N itens → `instagram:<code>:<n>` com URL
  `?img_index=<n>` (n estável — itens reprovados não renumeram). Guarda POR ITEM:
  confiança ALTA + nome + data resolvida (errar p/ o lado de NÃO criar). Preço do
  flyer vira lote sintético. Roda DEPOIS de `comum.aplicar()`, que apaga `lotes`.
  Specs: `20260710_camada-bronze/`, `-camada-prata/`, `-lotes-ingressos/`.
- `src/tratamento/slug.py` — o **endereço público**: `tratado.eventos.slug`
  (`<titulo-limpo>-<dd>-<mm>`, dia LOCAL de Brasília) e `tratado.filmes.slug`
  (`<titulo>-<ano>`, padrão IMDB). Roda DEPOIS da curadoria (nome e data são
  curáveis, e a URL segue a correção humana) e do enriquecer (o endereço limpo
  fica com o canônico). Escada de desempate: dia-mês → +ano (colisão entre anos)
  → ordinal (mesmo dia). Unicidade por **índice único**, não por convenção;
  `slug` NÃO entra em `comum.COLS_EVENTO` (a armadilha do `tipo`). Registra tudo
  em `operacao.slugs`, e é isso que faz link antigo virar 308 em vez de 404.
- `src/tratamento/sumido.py` — deriva `sumido` de `operacao.coletas`: evento FUTURO
  cujo `raspado_em` ficou atrás do início da última coleta boa da fonte não reapareceu
  no catálogo. As três guardas saem do SQL, não de `if` no orquestrador: fonte que
  falhou (`erro IS NULL`), fonte que coletou zero (`coletados > 0`, NI-59) e
  Instagram/cinema (`FORA`).
- `src/tratamento/ciclo.py` — o ciclo inteiro **numa transação só**, com `DELETE` e
  **não `TRUNCATE`**: `public` é view sobre `tratado`, então o site e o MCP consultam
  enquanto isto reconstrói. `TRUNCATE` é transacional mas toma `ACCESS EXCLUSIVE` — os
  leitores BLOQUEIAM em vez de enxergar a versão anterior. Nenhum passo do tratamento
  comita sozinho; quem comita é este.
- `src/tratamento/enriquecer.py` — enriquecimento v1 (regras, sem LLM): marca ruído
  (anúncio/curso, por palavra-chave no nome) e agrupa duplicatas — cross-fonte (mesmo
  dia + nome/local similares) e intra-fonte (regra mais apertada: mesmo local
  OBRIGATÓRIO + nome ≥ `SIM_NOME_INTRA`). "Mesmo dia" é o dia LOCAL de Brasília (bucket
  UTC separava 20h de 22h da mesma noite). **Marca, não apaga** — quem esconde é a
  consulta. `aplicar(con)` é idempotente. O dedupe também é a conciliação
  **Instagram ↔ plataforma** e **agenda ↔ post do dia**: os `local_aliases` da watchlist
  canonizam o local ("Culto" ↔ "Culto Rock Bar") via `aliases_local`; `instagram` é o
  último em `_PREF_FONTE` (quem vende o ingresso é o canônico; o post entra em
  `outras_urls`) e `preco_min` conta na completude.
- `src/servico/consulta.py` — **camada canônica**. `buscar_eventos(texto, cidade, data_inicio,
  data_fim, limite, incluir_ruido, bairro, tipo, gratis, perto_lat/lon)`, tudo
  opcional, retorno JSON-serializável. Por
  padrão esconde ruído, não-canônicos de dedupe, cancelados e **sumidos**; esgotado NÃO
  some (é resposta útil). O canônico traz `outras_urls`. `tipo` traz TAMBÉM os
  sem rótulo (a classificação é heurística, e esconder o que ela não soube
  classificar viraria ausência na tela); `perto_lat/lon` **ordenam, não filtram**
  (raio esconderia evento) e acrescentam `distancia_km`. `facetas_eventos()`
  devolve dias, bairros e as CONTAGENS por tipo — é com elas que o site decide
  se um filtro tem cobertura para existir. Toda função aceita `con=` opcional:
  uma requisição HTTP abre UMA conexão e a repassa (o handshake com o Neon custa
  mais que a query). `detalhar_evento(url)`
  aprofunda UM evento: descrição INTEIRA (a busca corta em `DESCRICAO_MAX`) + lotes — a
  condição do lote ("CORTESIA FEMININA ATÉ 00H") fica no nome cru de propósito: quem
  interpreta é o agente, não regex. No cinema, `buscar_filmes(...)` agrega por filme e
  `sessoes_filme(...)` detalha horários/salas/tipos/preço de UM filme.
- `src/servico/feedback.py` — o canal de feedback do site (NI-52): tipos fechados,
  tetos de tamanho, honeypot e teto por janela GLOBAL (sem IP, sem user-agent —
  a tabela mora em `uso` porque o contato é opcional e é dado pessoal). É a
  **primeira escrita** que o site faz na base; quem lê é
  `src/ferramentas/feedback.py`, e o relatório da rodada avisa os não lidos.
- `api/dados.py` — **API de leitura do site**. Ponte entre o front (JS) e a camada
  canônica (Python), **sem lógica própria**: as duas únicas transformações são de
  POSTURA — `descricao` sai em TRECHO (600 chars; a tool MCP segue integral, porque
  serve agente em contexto privado, não página indexada) e `organizador` NUNCA é
  exposto (às vezes é pessoa física → LGPD). Rotas sob `/api/dados/*`.
- `app/` + `lib/` — **site público** (Next.js App Router). Rotas: `/` (home),
  `/festas`, `/cinema`, `/evento/[slug]`, `/cinema/[slug]`, `/sobre`,
  `/feedback`. Os filtros vivem
  na URL (`?periodo=&texto=&gratis=&dia=&bairro=&tipo=&perto=`), não em estado
  de cliente: funciona sem JS, cada
  combinação é endereço compartilhável e o SSR entrega HTML pronto — que é o que a
  Fase 2 precisa que o buscador leia. Visual pelo **ZeroUm Design System**; nome do
  produto isolado em `lib/config.js` (é PROVISÓRIO, não espalhar). Imagens passam pelo
  `<Flyer>`/`<Cartaz>`, que só renderizam host de `HOSTS_IMAGEM`. `app/sitemap.js`,
  `app/robots.js` e `app/llms.txt/route.js` são a Porta B da Fase 2, e cada página de
  evento carrega JSON-LD `schema.org/Event`.
- `src/servico/mcp_server.py` — FastMCP expondo tools finas que delegam para `consulta.py`:
  `buscar_eventos`, `detalhar_evento`, `buscar_filmes`, `sessoes_filme` e `data_atual`
  (data/hora UTC + janela do fim de semana, p/ o agente montar "hoje"/"neste fim de
  semana"). Transporte stdio por default; `--http` sobe o MCP remoto (streamable HTTP
  stateless, porta da env `PORT`) — é o connector do celular.
- `src/servico/auth.py` — **OAuth do MCP remoto**. Este servidor é *resource server*: quem
  emite token é o **AuthKit (WorkOS)**; aqui só se verifica o JWT contra o JWKS do
  issuer, e o cliente descobre tudo sozinho (401 → RFC 9728 → DCR/CIMD → Bearer).
  Ligado por **env, não por flag**: `AUTHKIT_ISSUER` + `MCP_RECURSO` presentes = auth
  em `/mcp`; ausentes = modo antigo sob o prefixo secreto `MCP_SEGREDO` (o rollback,
  sem tocar em código). O caminho da rota SAI de `MCP_RECURSO`, para o metadado
  anunciado nunca divergir da rota servida. `mcp>=1.28` é piso duro.

### Fluxo (o que o `atualizar.py` orquestra) — DOIS TEMPOS

**1. Coleta (rede).** `raspar()` → `gravar()` em `cru.<fonte>` + `registrar_coleta()`
em `operacao.coletas` → descrever (incremental **pelo cru**: a fila é "não existe
payload de detalhe para este id", não `descricao IS NULL`) → precificar → cinema
(snapshot com poda de dias passados) → instagram (cru acumulativo + extração do flyer
só p/ post NOVO ≤ 60 dias; falha re-tenta na próxima rodada) → flyer para o storage.

**2. Tratamento (a seco), em `ciclo.executar`, numa transação só.**
`comum.aplicar()` → `instagram.aplicar()` → `cinema.aplicar()` → `sumido.aplicar()` →
`enriquecer.aplicar(aliases_local=...)` → `curadoria.aplicar()` → `slug.aplicar()` →
`reconstruir_fts()` (eventos E filmes) → **um commit**.

Depois: TMDB e cópia de pôster (que só sabem o que buscar depois de a grade existir,
então rodam entre um ciclo e outro — e disparam um segundo ciclo se trouxeram algo) →
poda do histórico do cru → relatório (compara com a rodada anterior e **ALERTA queda >
50%** — detector de scraper quebrado) → `registrar_execucao()`.

As filas de descrever/precificar leem `cru` + `operacao`, nunca `tratado` — é isso que
permite os dois rodarem antes de qualquer escrita na prata. E o parser é UM só: o
mesmo `tratamento/<fonte>.py` que depois monta o evento.

O FTS indexa nome/categoria/atrações/descrição + local_nome/organizador (para "o que
tem no Ordinário?" achar pela casa rotulada, mesmo com a legenda dizendo só "Ordi"); em
filmes, título/gêneros.

## Convenções e armadilhas

- **Schema unificado é o contrato, e quem o produz é o TRATAMENTO.** Fonte nova = um
  `coleta/<fonte>.py` (só fala com a fonte, devolve payload cru), um
  `tratamento/<fonte>.py` (`normalizar` + `DERIVACOES` + `LOTES`), uma tabela em
  `sql/cru/` e uma linha em `comum.TRILHAS` e `gravar.FONTES`.
- **Rótulo constante não é categoria.** `event_type='NORMAL'` do Sympla (224/224),
  `"MusicEvent"` do Shotgun (65/65) e `"Evento"` do Ticket and Go (71/72) foram todos
  gravados como `categoria` em algum momento: zero poder de distinção e poluição do
  FTS, que indexa a coluna. Antes de mapear um campo da fonte para `categoria`, conte
  os valores distintos. Um só = não é categoria, é flag.
- **Passo idempotente se compara TODAS as colunas que escreve.** O teste de
  idempotência do `enriquecer` passava havia semanas comparando três colunas enquanto
  a quarta (`dedupe_score`) variava a cada execução — o `SELECT` não tinha `ORDER BY` e
  o resultado dependia da ordem em que o Postgres devolvia as linhas. Query sem
  `ORDER BY` cujo resultado alimenta um cálculo é não determinismo esperando acontecer.
- **Datas em formatos mistos** (Sympla/Ingresse `+00:00`, Shotgun `.000Z`, Zig
  `.000-03:00`, Ticket and Go manda data e hora locais SEPARADAS e sem fuso). O parse
  mora em UM lugar: `src/base/tempo.py` (`instante` → datetime UTC; `norm_ts` → texto ISO
  comparável). Quem resolve é a **escrita**: `upsert_eventos` normaliza
  `start_date`/`end_date`/`raspado_em` (invariante: ISO UTC `+00:00`) e a `consulta.py`
  normaliza os parâmetros — a comparação no SQL é lexical e segura. Não grave data
  nessas colunas fora do upsert sem normalizar, nem reimplemente parse local.
- **`visto_em` é a âncora do `sumido`, e `raspado_em` do cru NÃO é.** No append-only,
  `cru.<fonte>.raspado_em` é a data da última MUDANÇA do payload; `visto_em` é a do
  último AVISTAMENTO, e avança em toda coleta sem custar linha nova. Usar o primeiro
  marcaria como "saiu do catálogo" todo evento que simplesmente não mudou desde a
  rodada passada. `tratado.eventos.raspado_em` sai do `visto_em` do CATÁLOGO — só dele:
  descrever e precificar têm timestamp próprio e não provam presença no catálogo.
- **Coleta ZERADA não é catálogo vazio** (NI-59): fonte que devolveu 0 nesta rodada
  fica FORA do `sumido` — hoje por `WHERE coletados > 0`, e não por `if` no meio da
  orquestração. Fonte que falhou também. Foi assim que o Shotgun
  quebrado no CI escondeu a própria agenda por três dias — coletou 0 **com sucesso** e
  todo evento futuro dele virou `sumido=1`. Pelo mesmo motivo, scraper que não
  conseguiu ler a listagem deve **LEVANTAR exceção, nunca devolver lista vazia**.
- **Cidade é rotulada, não lida do dado bruto:** no Shotgun ela vem como bairro em
  `addressLocality` (a cidade sai do parâmetro de busca, `cidade_label`); no Ticket and
  Go vem nula e quem decide é o `_do_df`, sem endereço nenhum.
- **Instagram tem regras próprias:** (a) URL de mídia do CDN **expira em horas** —
  baixar na hora da ingestão (`midias/instagram/`, gitignorado), nunca gravar a URL na
  base; (b) a fonte fica **FORA** do `sumido`, duas vezes: não registra linha em
  `operacao.coletas` e ainda está em `sumido.FORA` (post que sai da 1ª página do perfil
  não significa cancelamento); (c) a watchlist é dado **curado à mão e versionado** —
  não mover para a base; (d) a extração do flyer roda na ASSINATURA (`claude -p`) e é
  incremental — nunca re-extrai shortcode que já tem origem `extracao` no cru.
- **URLs do Bileto (`bileto.sympla.com.br`) não passam pelo "descrever":** o id no fim
  delas é de OUTRO namespace, e o BFF de página devolveria um evento alheio sem erro
  HTTP. Além do filtro de URL, o `_descrever` valida o nome devolvido
  (`texto.mesmo_nome`) antes de gravar no cru — **não remova essa guarda**. E ela roda
  SÓ na coleta, de propósito: repeti-la na leitura do payload foi medido contra a base
  real e descartava descrição boa toda vez que o produtor renomeava o evento entre uma
  raspagem e outra (o nome do catálogo se move; a comparação só vale fresca).
- **`loading.jsx` custa o status HTTP da rota inteira, inclusive das filhas.**
  Ele cria uma fronteira de Suspense, e o Next despacha um shell **200** antes de
  resolver a página — então `notFound()` e `permanentRedirect()` acontecem no
  CLIENTE. O 404 vira soft-404 e o 308 vira redirecionamento que só navegador
  executa: para o buscador, o endereço antigo continua sendo uma página que
  responde 200. Medido no build de produção em 29/07 (no `dev` é igual, mas só o
  build prova). E a fronteira desce a árvore: `app/cinema/loading.jsx` cobria
  também `app/cinema/[slug]`, por isso a lista mora num route group
  `app/cinema/(lista)/` — o grupo não aparece na URL e mantém o esqueleto na
  lista sem estragar o status do detalhe. Colocar `loading.jsx` num segmento com
  filhas que dependem de status HTTP é o jeito silencioso de quebrar SEO.
  Testar redirecionamento com `curl -o /dev/null -w '%{http_code}'` no
  `next start`, nunca só clicando no navegador — no navegador os dois passam.
- **`loading.jsx` NÃO cobre troca de filtro.** Ele só entra quando o SEGMENTO
  de rota muda, e `/festas?periodo=hoje` → `?periodo=7d` é a mesma rota — ou
  seja, justamente o gesto de que o beta reclamou ficava sem sinal de vida. O
  que resolve é `<Suspense key={filtros}>` em volta da parte que depende da
  base: cada combinação vira uma fronteira nova, que suspende. Ao acrescentar
  filtro na página, acrescente-o à `key` também.
- **`least(1, NULL)` no Postgres devolve 1**, não NULL — ele ignora nulos,
  diferente de quase todo operador. Na haversine do "perto de mim" isso fazia
  todo evento sem coordenada (30% da base) sair com `acos(1) = 0`, ou seja
  "0,0 km": exatamente onde a pessoa está. Guarda explícita com `CASE WHEN`.
- **Função não atravessa a fronteira server → client.** Passar `href={(x) =>
  ...}` para um client component faz o React DESCARTAR o componente — a página
  renderiza sem ele, sem erro na tela. O padrão do projeto é passar `base` +
  `estado` (strings) e montar a URL do lado do cliente (ver `DropFiltro`,
  `PertoDeMim`).
- **PostHog no ambiente local: a key precisa existir em Development.** Sem
  `NEXT_PUBLIC_POSTHOG_KEY`, o `instrumentation-client.js` nem chama `init()` — e
  o único sinal é um `console.error` no navegador, então o `npm run dev` roda com
  a analytics inteira desligada sem nada quebrar. A variável mora no ambiente
  **Development** da Vercel; `vercel env pull .env.local --environment=development`
  a traz de volta (o pull SOBRESCREVE o arquivo — é por isso que ela precisa estar
  lá, e não só na máquina). Dev, preview e produção mandam para o mesmo projeto:
  quem separa é a propriedade `ambiente` de todo evento, que o filtro de contas de
  teste do projeto usa para tirar `development`/`preview` dos insights. Ao olhar um
  número, é o "Filter out internal and test users" que decide se você está vendo
  gente de verdade.
- **`posthog-js` descarta evento de quem ele julga bot, em silêncio.** A checagem
  (`aa()` no `dist/module.js`) olha três coisas: a string do user-agent, os
  `brands` de `navigator.userAgentData` — que no Chromium headless trazem
  "HeadlessChrome" — e `navigator.webdriver`. Vale para o Playwright: um teste de
  ponta a ponta da analytics precisa mascarar as TRÊS, senão a página carrega, o
  SDK inicializa, o console mostra tudo funcionando e nenhum evento sai. O que
  denuncia é `[WebExperiments] Refusing to render ... likely bot` no console.
- **Máscara de dado sensível varre TUDO, não uma lista de campos.** O `?perto=`
  saía mascarado de cinco chaves conhecidas (`$current_url`, `$referrer`…) — e
  o SDK, numa versão qualquer, passou a mandar `$session_entry_url`, que não
  estava na lista e levava a coordenada inteira para o PostHog. Ninguém é
  avisado quando isso acontece: o campo novo simplesmente aparece. Hoje o
  `before_send` percorre toda chave de texto de `properties`, `$set` e
  `$set_once` (o hook antigo, `sanitize_properties`, nem enxergava os dois
  últimos, onde mora o `$initial_current_url` do perfil da pessoa). Ao proteger
  um parâmetro novo, proteja por PADRÃO do valor, nunca por nome de campo.
- **Endereço público é DADO, não cálculo na borda.** O `slug` de evento e de
  filme é coluna da prata, atribuída por `tratamento/slug.py`; o front usa
  `ev.slug`/`filme.slug` e **não existe regra de slug em JavaScript**. A razão é
  a de sempre: duas implementações da mesma regra em duas linguagens divergem, e
  aqui a divergência não seria um título feio — seria 404. A resolução é uma
  regra só, sem farejar formato: *se o slug do registro difere do parâmetro da
  rota, 308 para o do registro* — cobre id antigo (`sympla~3520331`, que o
  farejador da `consulta.py` ainda entende), slug de antes de um renome (via
  `operacao.slugs`), filme por id numérico ou sem o ano, e duplicata → canônico.
  Spec: `docs/specs/20260729_urls-semanticas/`.
- **Ruído conhecido:** o filtro `themes=99` do Sympla deixa passar anúncios/cursos —
  tratados pelo filtro v1 de `enriquecer.py` (na dúvida, a regra NÃO marca: falso
  positivo esconde festa real; termos já descartados em `docs/backlogs/rejeitado.yaml`).
  `end_date` às vezes vem inconsistente na origem — filtre por `start_date`.
- **Schema mudou? NUNCA `DROP SCHEMA` — o `cru` mora aqui.** A convenção antiga
  ("base descartável") é da era SQLite, ANTES da bronze, e custou o catálogo inteiro do
  Shotgun num drop. Hoje: (a) mudança ADITIVA = `ADD COLUMN IF NOT EXISTS` /
  `CREATE TABLE IF NOT EXISTS` no próprio `sql/<camada>/<tabela>.sql` — idempotente, o
  `conectar()` aplica sozinho; (b) NÃO-ADITIVA = dropar SÓ as derivadas afetadas
  (`tratado` inteira é 100% reconstruível desde a fatia 7 da spec do medalhão)
  e re-derivar; (c) os schemas `cru`, `curado`, `operacao` e `uso` **não se
  reconstroem** — não dropar; se algo destrutivo for inevitável, exportar antes
  (NI-56).
- **MCP / FastMCP:** retorno `list` vira `structuredContent["result"]` + um content
  block por item; retorno `dict` vira content block único. `tests/test_mcp_server.py`
  lida com os dois formatos. Config em `.mcp.json`; setup dos clientes em
  `docs/TESTE_MCP.md`.
- **Roteamento do `vercel.json` — duas portas no mesmo domínio.** Não há catch-all: são
  rewrites explícitas e o Next fica com o resto (páginas, sitemap, robots, llms.txt).
  As do MCP são três: `/mcp`, `/.well-known/oauth-protected-resource/:recurso*`
  (descoberta da RFC 9728 — **sem ela o cliente nunca sabe onde autenticar**, e o Next
  devolveria 404) e `/:segredo/mcp`, resquício do modo anterior — essa última **não** é
  o segredo literal (ele vem da env `MCP_SEGREDO` e não pode ser versionado): o padrão
  casa qualquer primeiro segmento terminando em `/mcp` e quem valida é o app ASGI.
  **Mexer aqui é o jeito mais fácil de derrubar o MCP sem perceber** — depois de
  alterar, confira que o connector ainda responde. O `vercel.json` não aceita comentário
  (nem `$comment`: o schema rejeita propriedade extra e o deploy falha), por isso a
  explicação mora aqui.

## Estratégia de commit

O usuário commita **em partes lógicas** e prefere disparar ele mesmo ("segue").
Não faça commit sem pedido. Mensagens em português.

## Documentos de referência

- `docs/PRD_MVP.md` — **fonte da verdade atual**: visão, escopo, moat, modelo de
  distribuição, roadmap por fases (0/1/2).
- `docs/PRD_POC.md` — registro histórico da prova de conceito.
- `docs/backlogs/` — backlog em dois YAMLs filtráveis: `nao-iniciado.yaml` (abertos,
  com campo `status`) e `rejeitado.yaml` (testado e descartado). Implementado de verdade
  sai da lista (git/spec registram).
- `docs/specs/` — specs técnicas de implementação (o "como" de cada item, uma pasta
  datada por spec com `spec.md`). Ver `docs/specs/README.md`. Vale ler antes de mexer
  na área correspondente — é onde vive o histórico das decisões resumidas aqui.
  Destaques: `20260726_abrir-ao-publico/` (o plano de abrir a terceiros — LICENSE,
  cron, site, instrumentação, JSON-LD/sitemap; **implementada**, incluindo o OAuth do
  MCP), com os anexos `tos.md` (postura sobre Termos de Uso: **agregador com
  atribuição** — leia antes de mexer no que o site expõe) e `cron.md`;
  `20260727_rework-pagina-cinema/` (implementada); `20260728_arquitetura-medalhao/`
  (**implementada** — as camadas viraram schemas e a prata se reconstrói do cru;
  a §13.1 registra os três achados que a reconstrução contra a base real
  produziu, e é a leitura mais curta sobre por que o desenho é esse) e
  `20260728_rework-site/` (**implementada** — o rework do site pós-beta:
  eventos + usabilidade transversal. Tem duas seções que valem por si: a §0.2 é
  o que a leitura do código desmentiu do plano escrito um dia antes, e a **§14 é
  o que a base real desmentiu do plano na hora de executar** — inclusive dois
  bugs que só apareceram rodando, e os dois itens que ficaram parciais por
  cobertura de dado, não por código).
- `docs/TESTE_MCP.md` — como plugar o MCP server nos clientes de IA.
