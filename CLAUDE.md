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

# Atualização sob demanda — raspa as 5 fontes → marca sumidos → descreve/precifica
# → cinema → Instagram → deriva → enriquece → FTS → relatório de saúde → grava a
# rodada em `execucoes`. Rodar antes de usar o agente.
python src/pipeline/atualizar.py
python src/pipeline/atualizar.py --sem-shotgun           # pula Shotgun (lento, usa navegador)
python src/pipeline/atualizar.py --sem-cinema            # pula a grade de cinema
python src/pipeline/atualizar.py --sem-tmdb              # pula o enriquecimento TMDB dos filmes
python src/pipeline/atualizar.py --sem-instagram         # pula o Instagram (Monid + claude -p)
python src/pipeline/atualizar.py --sem-extracao-flyer    # Instagram só até a Bronze, sem a visão
python src/pipeline/atualizar.py --rodada-local          # o que o CI não faz: Shotgun + fila de
                                                #   extração de flyer (--so-instagram é
                                                #   o nome antigo, continua valendo)
python src/pipeline/atualizar.py --precificar-tudo       # tickets de TODOS os futuros (default: 30 dias)
python src/pipeline/atualizar.py --so-derivar            # não raspa; re-deriva do bruto + regras + FTS
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
python tests/test_bronze.py                     # Bronze/Prata (eventos_raw, lotes, derivação) + guarda anti-Bileto
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

Duas frentes acopladas por uma base única — **Postgres no Neon** (driver psycopg 3;
antes era SQLite local). A connection string vem de `EVENTOS_DB_URL` (env, com
fallback no `.env` da raiz — resolvido por `store.env_var`); testes usam
`EVENTOS_DB_URL_TESTE`. Spec: `docs/specs/20260711_consulta-na-nuvem/`.

```
src/
  store.py  consulta.py  enriquecer.py  derivar.py  tempo.py  # núcleo (imports irmãos)
  auth.py                                         # verifica o token OAuth do MCP remoto
  midia.py                                        # upload p/ storage próprio (Vercel Blob)
  atualizar.py  mcp_server.py                     # entrypoints
  scrapers/
    sympla.py  ingresse.py  shotgun.py  zig.py  ticketandgo.py  cinema.py  instagram.py  tmdb.py  discover_sympla.py
api/           # funções serverless (Vercel; deps: pyproject.toml da raiz)
  index.py     #   MCP remoto (ASGI do FastMCP)
  dados.py     #   API de leitura do site — traduz querystring p/ consulta.py
app/  lib/     # front Next.js (App Router) do site público — NA RAIZ, não em web/
.github/workflows/raspar.yml   # cron diário da raspagem (NI-10)
sql/           # schema.sql + reconstruir_fts.sql (fonte única do DDL, roda no DBeaver/psql)
dados/         # dado curado à mão, versionado (perfis_instagram.yaml — a watchlist;
               #   locais_df.yaml — casas DF que ancoram o recorte do Ticket and Go)
docs/          # PRD, backlogs/, specs/
tests/         # scripts executáveis + base_teste.py (redireciona p/ eventos_teste)
```

**O front mora na RAIZ (`app/`, `lib/`, `package.json`), não numa subpasta.** É o
arranjo que a Vercel suporta para framework + funções Python no mesmo projeto. Com o
front em subpasta seria preciso configurar Root Directory e "include files outside
root" no dashboard — configuração invisível no repo, que quebra em silêncio.

**O DDL não fica em string Python:** mora em `sql/schema.sql` e é carregado por
`store.conectar()`. Ao mudar o schema, edite o `.sql`. O SQL dinâmico (upsert,
updates de derivação/enriquecimento) segue no código, porque não roda standalone.

**Rodar entrypoints a partir da raiz** do repo (ex.: `python src/pipeline/atualizar.py`); o
`sys.path[0]` vira `src/`, então `import store`/`import consulta` resolvem como
irmãos, e os entrypoints importam scrapers via `from scrapers import ...`.

### Frente A — Raspagem

Um módulo por fonte em `src/coleta/`, cada um com `raspar(...)` devolvendo lista de
dicts já normalizados para o schema unificado (exceções: cinema e instagram têm
contrato próprio). Cada scraper preenche `ULTIMA_RASPAGEM` com `coletados`/
`total_site` — é daí que o `atualizar.py` mede cobertura.

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
  `escolhido=None` e o filme fica sem nota). Incremental por filme novo. Bronze própria
  `cinema_extra_raw` (PK filme_id+origem), **acumulativa** — sobrevive ao snapshot de
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
- **midia.py** — storage próprio (**Vercel Blob**): pôster de filme e flyer do
  Instagram. Pathname ESTÁVEL (sem sufixo aleatório): re-subir substitui.
  `BLOB_READ_WRITE_TOKEN` no env; sem ele os passos são pulados e o front cai no
  hotlink da fonte. Hosts permitidos em `lib/imagens.mjs` (`HOSTS_IMAGEM`).
- **discover_sympla.py** — ferramenta de reconhecimento, fora do pipeline: intercepta
  XHR/fetch num navegador para achar a API interna quando um site muda.

### Frente B — Consulta

- `src/store.py` — aplica o schema + `upsert_eventos` (chave `<fonte>:<id_nativo>`;
  **normaliza as datas na escrita**) + busca textual pela coluna `busca tsvector`
  (config `pt`: unaccent + stemming). Depois de raspar, `reconstruir_fts(con)`. A chave
  reservada `_raw` do dict normalizado vai para a **Bronze** (`eventos_raw`, PK
  `evento_id+origem` — Sympla tem 2 payloads: catálogo e detalhe).
- `src/tratamento/derivar.py` — derivação a seco (**camada Prata**): recalcula colunas de
  `eventos` e a tabela `lotes` a partir de `eventos_raw`, sem rede. Campo novo do bruto
  = função aqui + `--so-derivar`, **sem re-raspar**; idempotente. Lote guarda o nome CRU
  da fonte e `preco` = total com taxa; `preco_min` é o menor lote **PAGO** (cortesia não
  mascara o preço real) e `tem_gratis` marca lote grátis não esgotado. Os payloads de
  tickets vêm do passo "precificar" — **não incremental** (preço é volátil), só na
  janela de 30 dias, e no Sympla só para eventos com descrição validada (âncora da
  guarda anti-Bileto).
  `aplicar_cinema(con)` reconstrói `filmes`/`sessoes` do zero a partir de `cinema_raw`
  (**SNAPSHOT**: sessão não tem id estável entre semanas — sem upsert, sem dedupe, sem
  `sumido`; o id do FILME é estável e é a PK). `aplicar_instagram(con)` reconstrói os
  eventos `fonte='instagram'` do zero (a "Prata" do Instagram é a própria `eventos`):
  post comum = 1 item → `instagram:<code>`; carrossel-agenda = N itens →
  `instagram:<code>:<n>` com URL `?img_index=<n>` (n estável — itens reprovados não
  renumeram). Guarda POR ITEM: confiança ALTA + nome + data resolvida (errar p/ o lado
  de NÃO criar). Preço do flyer vira lote sintético. Roda DEPOIS de `aplicar()`, que
  trunca `lotes`. Specs: `20260710_camada-bronze/`, `-camada-prata/`,
  `-lotes-ingressos/`.
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
  data_fim, limite, incluir_ruido)`, tudo opcional, retorno JSON-serializável. Por
  padrão esconde ruído, não-canônicos de dedupe, cancelados e **sumidos**; esgotado NÃO
  some (é resposta útil). O canônico traz `outras_urls`. `detalhar_evento(url)`
  aprofunda UM evento: descrição INTEIRA (a busca corta em `DESCRICAO_MAX`) + lotes — a
  condição do lote ("CORTESIA FEMININA ATÉ 00H") fica no nome cru de propósito: quem
  interpreta é o agente, não regex. No cinema, `buscar_filmes(...)` agrega por filme e
  `sessoes_filme(...)` detalha horários/salas/tipos/preço de UM filme.
- `api/dados.py` — **API de leitura do site**. Ponte entre o front (JS) e a camada
  canônica (Python), **sem lógica própria**: as duas únicas transformações são de
  POSTURA — `descricao` sai em TRECHO (600 chars; a tool MCP segue integral, porque
  serve agente em contexto privado, não página indexada) e `organizador` NUNCA é
  exposto (às vezes é pessoa física → LGPD). Rotas sob `/api/dados/*`.
- `app/` + `lib/` — **site público** (Next.js App Router). Rotas: `/` (home),
  `/festas`, `/filmes`, `/evento/[id]`, `/sobre`. Os filtros vivem na URL
  (`?periodo=&texto=&gratis=`), não em estado de cliente: funciona sem JS, cada
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

### Fluxo (o que o `atualizar.py` orquestra)

`raspar()` → `upsert_eventos()` (grava o bruto na Bronze junto) → marcar sumidos →
descrever (incremental; o upsert usa COALESCE p/ nunca zerar a descrição) → precificar
→ cinema (snapshot com poda de dias passados) → instagram (Bronze acumulativa +
extração do flyer só p/ post NOVO ≤ 60 dias; falha re-tenta na próxima rodada) →
`derivar.aplicar()` + `aplicar_instagram()` + `aplicar_cinema()` →
`enriquecer.aplicar(aliases_local=...)` → `reconstruir_fts()` (eventos E filmes) →
relatório (compara com a rodada anterior e **ALERTA queda > 50%** — detector de scraper
quebrado) → `registrar_execucao()` (uma linha por rodada, com erros POR evento).

O FTS indexa nome/categoria/atrações/descrição + local_nome/organizador (para "o que
tem no Ordinário?" achar pela casa rotulada, mesmo com a legenda dizendo só "Ordi"); em
filmes, título/gêneros.

## Convenções e armadilhas

- **Schema unificado é o contrato.** Todo scraper normaliza para os campos de
  `sql/schema.sql` antes de gravar. Fonte nova segue o mesmo `_normalizar(...)` → dict.
- **Datas em formatos mistos** (Sympla/Ingresse `+00:00`, Shotgun `.000Z`, Zig
  `.000-03:00`, Ticket and Go manda data e hora locais SEPARADAS e sem fuso). O parse
  mora em UM lugar: `src/base/tempo.py` (`instante` → datetime UTC; `norm_ts` → texto ISO
  comparável). Quem resolve é a **escrita**: `upsert_eventos` normaliza
  `start_date`/`end_date`/`raspado_em` (invariante: ISO UTC `+00:00`) e a `consulta.py`
  normaliza os parâmetros — a comparação no SQL é lexical e segura. Não grave data
  nessas colunas fora do upsert sem normalizar, nem reimplemente parse local.
- **`raspado_em` é a âncora do `sumido`:** só o upsert do catálogo o atualiza
  (descrever/precificar mexem em outras colunas). Atualizá-lo fora do upsert quebra a
  detecção de evento sumido.
- **Coleta ZERADA não é catálogo vazio** (NI-59): fonte que devolveu 0 nesta rodada
  fica FORA do `_marcar_sumidos`, como já ficava a que falhou. Foi assim que o Shotgun
  quebrado no CI escondeu a própria agenda por três dias — coletou 0 **com sucesso** e
  todo evento futuro dele virou `sumido=1`. Pelo mesmo motivo, scraper que não
  conseguiu ler a listagem deve **LEVANTAR exceção, nunca devolver lista vazia**.
- **Cidade é rotulada, não lida do dado bruto:** no Shotgun ela vem como bairro em
  `addressLocality` (a cidade sai do parâmetro de busca, `cidade_label`); no Ticket and
  Go vem nula e quem decide é o `_do_df`, sem endereço nenhum.
- **Instagram tem regras próprias:** (a) URL de mídia do CDN **expira em horas** —
  baixar na hora da ingestão (`midias/instagram/`, gitignorado), nunca gravar a URL na
  base; (b) a fonte fica **FORA** do `_marcar_sumidos` (post que sai da 1ª página do
  perfil não significa cancelamento); (c) a watchlist é dado **curado à mão e
  versionado** — não mover para a base; (d) a extração do flyer roda na ASSINATURA
  (`claude -p`) e é incremental — nunca re-extrai shortcode que já tem origem
  `extracao` na Bronze.
- **URLs do Bileto (`bileto.sympla.com.br`) não passam pelo "descrever":** o id no fim
  delas é de OUTRO namespace, e o BFF de página devolveria um evento alheio sem erro
  HTTP. Além do filtro de URL, o `_descrever` valida o nome devolvido (`_mesmo_nome`)
  antes de gravar — **não remova essa guarda**.
- **Ruído conhecido:** o filtro `themes=99` do Sympla deixa passar anúncios/cursos —
  tratados pelo filtro v1 de `enriquecer.py` (na dúvida, a regra NÃO marca: falso
  positivo esconde festa real; termos já descartados em `docs/backlogs/rejeitado.yaml`).
  `end_date` às vezes vem inconsistente na origem — filtre por `start_date`.
- **Schema mudou? NUNCA `DROP SCHEMA` — a Bronze mora aqui.** A convenção antiga
  ("base descartável") é da era SQLite, ANTES da Bronze, e custou o catálogo inteiro do
  Shotgun num drop. Hoje: (a) mudança ADITIVA = `ADD COLUMN IF NOT EXISTS` /
  `CREATE TABLE IF NOT EXISTS` no próprio `sql/schema.sql` — idempotente, o
  `conectar()` aplica sozinho; (b) NÃO-ADITIVA = dropar SÓ as derivadas afetadas
  (`lotes`, `filmes`, `sessoes` são 100% reconstruíveis; `eventos` ainda NÃO é — NI-55)
  e re-derivar; (c) `eventos_raw`, `instagram_raw`, `cinema_raw`, `cinema_extra_raw`,
  `execucoes`, `usuarios` e `acessos` **não se reconstroem** — não dropar; se algo
  destrutivo for inevitável, exportar antes (NI-56).
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
  `20260727_rework-pagina-cinema/` (implementada) e `20260727_rework-eventos/`
  (**especificada, aguardando implementação**).
- `docs/TESTE_MCP.md` — como plugar o MCP server nos clientes de IA.
