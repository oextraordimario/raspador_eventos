# Spec — Rework de eventos pós-beta (NI-38/39/41/43/44/45/46/47)

> **Status:** especificada em 2026-07-27, aguardando implementação.
> **O quê/por quê:** rodada de feedback do beta (autor + vários amigos,
> 27/07) rendeu 19 pedidos, todos registrados no backlog (NI-38 a NI-54).
> Esta spec cobre SÓ a parte de eventos executável com **dado que já existe
> na base** — mesmo quando exige mudar tratamento ou modelagem. Fica de fora
> tudo que depende de raspagem nova (NI-48), de classificador LLM (NI-42,
> NI-49) ou que é transversal ao site (NI-50 a NI-54).
>
> **Contexto:** a página `/festas` tem card enxuto (sem resumo), três
> períodos fixos (hoje/fds/7d) e busca textual — e a busca por casa, que o
> FTS foi feito para atender, falha na prática no site (§2). O cinema já
> passou pelo rework equivalente (spec `20260727_rework-pagina-cinema/`);
> vários padrões de lá se reaproveitam aqui (calendário, facetas na resposta,
> filtros na URL).

---

## 1. O pedido → o que entra

| Feedback | NI | Nesta spec? |
|---|---|---|
| resumo do evento no card | NI-38 | **sim** (§4.1) — a API já manda `descricao` |
| localização Maps | NI-39 | **sim** (§4.2) — `endereco`/`lat`/`lon` existem |
| pesquisar por casa ("Ordinário" deu erro) | NI-41 | **sim** (§3) — bug de UX/consulta, dado existe |
| filtro por data com calendário | NI-43 | **sim** (§5.1) — componente do cinema + faceta nova |
| separar festas & baladas × shows & festivais | NI-44 | **sim** (§5.3) — heurística sobre colunas existentes |
| filtro por bairro | NI-45 | **sim** (§5.2) — coluna existe; melhorar derivação |
| eventos perto de mim | NI-46 | **sim, condicionada** (§6) — lat/lon existem; medir cobertura |
| filtro sazonal (junina, natal) | NI-47 | **sim** (§5.4) — busca FTS pré-montada, zero schema |
| expandir o card no clique | NI-40 | não — prioridade baixa do autor, checar UX antes |
| "eventos parecidos" | NI-42 | não — anotado; depende do NI-05 (LLM) |
| eventos culturais / outras categorias | NI-48 | não — raspagem nova + decisão de escopo do PRD |
| LGBT-friendly e vibes | NI-49 | não — classificação sensível, é tag do NI-05 |

## 2. Inventário — o que a base já tem

Verificado no código E **medido na base real em 2026-07-27** (285 eventos
futuros visíveis — sem ruído/sumido/cancelado; o Shotgun não aparece porque
a fonte está quebrada, NI-31):

| fonte | futuros | com lat | com bairro | com descrição |
|---|---|---|---|---|
| sympla | 181 | 181 (100%) | 83 (46%) | 166 (92%) |
| ticketandgo | 75 | **0** | 0 | 75 (100%) |
| instagram | 22 | 0 | 0 | 22 (100%) |
| ingresse | 5 | 5 (100%) | 0 | 5 (100%) |
| zig | 2 | 0 | 2 | 2 |
| **total** | **285** | **186 (65%)** | **85 (30%)** | **270 (95%)** |

Surpresa da medição: o scraper do Ticket and Go MAPEIA `latitude`/
`longitude` mas a fonte manda nulo — a 2ª maior fonte de futuros está 100%
sem coordenada. E a cobertura de `bairro` (30%) confirma que a extração
textual do §5.2 é o que destrava o filtro (o Ticket and Go tem
`endereco_completo` textual esperando isso).

| Precisa de | Já existe? | Onde |
|---|---|---|
| Resumo do evento | **SIM** | `descricao` — a listagem da API já devolve trecho de 600 chars (`api/dados.py DESCRICAO_SITE`); o card simplesmente não usa |
| Endereço p/ Maps | SIM | `endereco`, `local_nome`, `cidade`; `lat`/`lon` normalizados pelas **5** fontes (sympla, ingresse, shotgun, zig, ticketandgo) |
| Bairro | PARCIAL | coluna `bairro` derivada só de Sympla (`location.neighborhood`) e Zig (`event_location.neighborhood`); Shotgun guarda o bairro em `endereco` (o `addressLocality` deles é bairro); Ticket and Go tem `endereco_completo` textual na Bronze; Instagram fica nulo (NI-16) |
| Dias com evento (calendário) | derivável | `start_date` (ISO UTC, comparação lexical) → dia local, mesmo desenho de `facetas_filmes()["dias"]` |
| Tipo festa × show | derivável | `categoria` (real do Sympla, não confiável sozinha — NI-04), `nome`, `descricao`, `atracoes` |
| Busca por casa | **SIM** | o FTS indexa `local_nome`/`organizador` desde a v1.1 — o problema é outro (§3) |
| Calendário (UI) | SIM | `app/filmes/Calendario.jsx` (NI-35), a generalizar |

Conclusão que molda a spec: **quase tudo é exposição de dado que já existe**
(front + parâmetro de consulta + faceta). A única mudança de schema é a
coluna `tipo` (§5.3) — e por ser ADITIVA ela **não aciona a convenção de
dropar a base**: um `ALTER TABLE eventos ADD COLUMN IF NOT EXISTS tipo TEXT`
no próprio `sql/schema.sql` é idempotente, o `conectar()` aplica sozinho e
nada se perde (nem os dados congelados do Shotgun quebrado, NI-31). A
convenção do drop segue valendo para mudança não-aditiva — só não é o caso
aqui. `tipo` e `bairro` são preenchidos a seco (`--so-enriquecer` /
`--so-derivar`), sem re-raspar.

## 3. NI-41 — a busca por casa que "deu erro"

**Diagnóstico CONFIRMADO na base real (2026-07-27):** não é o FTS — é a
interação busca × período. Medido: `websearch_to_tsquery('pt', 'Ordinário')`
vira `'ordinari'` e casa com TODOS os ~40 eventos da casa na base
(`local_nome = "Ordinário Bar & Música"`, majoritariamente canônicos,
`ruido=0`, `sumido=0`); a conciliação Instagram↔plataforma está íntegra. O
que quebra é o front: `app/festas/page.jsx` usa `periodo = sp?.periodo ??
'hoje'` — quem digita "Ordinário" busca a agenda da casa, mas o site
responde "a agenda da casa HOJE". No dia do teste, o único evento do dia
(Segunda da Resenha, 00h local) já tinha começado quando a busca rodou
(`data_inicio = agora`) → zero resultados, com cara de busca quebrada. O
texto do vazio ainda sugere "amplie o período" — o sistema sabe o que
aconteceu e mesmo assim erra o default.

**Correção desenhada:**

1. **Com `texto` preenchido e SEM período explícito na URL, a janela vira
   "todos os futuros"** (`data_inicio = agora`, sem `data_fim`). Período
   escolhido de propósito (chip clicado → `?periodo=` na URL) continua
   respeitado — a regra é só sobre o default. Implementação no front (é o
   front que inventa o default `hoje`; a API já aceita janela aberta).
2. Chip novo **"próximos"** em `PERIODOS` (`lib/config.js`) para esse estado
   ter representação visível e endereço compartilhável (`?periodo=proximos`)
   — vira também o chip ativo quando a regra 1 dispara, então a UI nunca
   mente sobre a janela em uso.
3. ~~Verificação de FTS~~ **já feita no diagnóstico** (acima): o FTS casa;
   nenhuma correção de busca/dedupe necessária. Se um caso análogo aparecer
   em outra casa, o roteiro de diagnóstico fica em anexo mental: tsquery →
   flags do evento → default de período.

Teste de regressão em `tests/test_api_dados.py`: busca com texto e sem
período devolve evento de daqui a N dias.

## 4. Card e detalhe (NI-38, NI-39)

### 4.1 Resumo no card

Zero backend. No `Card` de `app/festas/page.jsx`, um parágrafo com
`line-clamp` de 2 linhas usando a `descricao` que a resposta já traz.
Regras de densidade (o card já tem line-up + meta):

- com `atracoes` presentes, o line-up continua tendo prioridade visual; o
  resumo entra abaixo, em corpo menor (mesma hierarquia do card de filme
  pós-NI-35: título > metadados > sinopse);
- descrição ausente = nada renderiza (sem placeholder);
- o corte é do CSS (`-webkit-line-clamp`), não de JS — o trecho de 600 da
  API é sobra suficiente.

### 4.2 Link "ver no mapa"

No bloco "where" de `app/evento/[id]/page.jsx`, link externo para o Google
Maps **sem API key e sem embed** (decisão: iframe pesa e exige chave para
nada; o clique resolve "como chego lá"):

    https://www.google.com/maps/search/?api=1&query=<lat>,<lon>      # quando houver
    https://www.google.com/maps/search/?api=1&query=<local_nome, endereco, cidade>  # fallback textual

Com `lat`/`lon` presentes, coordenada vence (endereço textual das fontes às
vezes é sujo). `rel="noopener"`, `target="_blank"`, mesmo padrão dos CTAs.
Card NÃO ganha o link no v1 (clique no card já navega para o detalhe; dois
alvos no mesmo card é armadilha de toque no mobile).

## 5. Filtros novos na `/festas`

Filosofia inalterada (spec do site): filtros **vivem na URL**, funcionam sem
JS, SSR. Parâmetro novo entra em `consulta.buscar_eventos()` (nunca lógica
na API), a `api/dados.py` só traduz querystring, o MCP herda de graça.

### 5.1 Calendário de data (NI-43)

- **Faceta:** `facetas_eventos()` nova em `consulta.py` devolvendo
  `{"dias": [...], "bairros": [...], "tipos": [...]}` — calculada só sobre
  evento futuro visível (mesmos filtros default da busca: sem ruído, sem
  sumido, sem cancelado, só canônico). `dias` = dia **LOCAL simples** de
  Brasília do `start_date` (`to_char(... AT TIME ZONE 'America/Sao_Paulo',
  'YYYY-MM-DD')`).
  **Decisão do corte:** o dia do calendário é o dia local SIMPLES
  (00:00–24:00), consistente com o agrupamento visível da lista
  (`agruparPorDia`/`chaveDia`, que não desloca 6h) — uma festa de sábado 1h
  aparece agrupada em "sábado" na tela, então o dia "sábado" do calendário
  tem que trazê-la. O corte das 6h continua valendo onde sempre valeu: nos
  atalhos de período (`_janela`) e nos rótulos "hoje/amanhã".
- **API:** a resposta de `/api/dados/eventos` ganha o campo `facetas` (mesmo
  padrão do `/filmes`: junto na resposta, sem round-trip extra).
- **Front:** generalizar `app/filmes/Calendario.jsx` (hoje acoplado à rota
  `/filmes`?) para receber a rota-base e os dias habilitados; dia sem evento
  fica desabilitado. Selecionar dia escreve `?de=YYYY-MM-DDT00:00:00-03:00&
  ate=YYYY-MM-DDT23:59:59-03:00` (a API já aceita `de/ate`; nenhum parâmetro
  novo). Faixa de datas (de–até em dois cliques) fica para um passo 2, se o
  dia único se provar curto.

### 5.2 Filtro por bairro (NI-45)

Duas metades:

1. **Cobertura (derivação, sem re-raspar).** Passo novo em
   `derivar.aplicar()`: quando `bairro IS NULL` e há `endereco`, extrair o
   bairro por dicionário textual das RAs/regiões de Brasília (Asa Sul, Asa
   Norte, Taguatinga, Águas Claras, Sudoeste, Lago Sul/Norte, Ceilândia,
   Guará, Setores SCES/SCLS/SHIS..., lista curada em constante do
   `derivar.py`). Conservador como sempre: sem casamento claro, fica nulo.
   Normalização de grafia junto (unaccent + caixa) para a faceta não listar
   "ASA NORTE" e "Asa Norte" como dois bairros. É derivação a seco —
   `--so-derivar` reprocessa a base inteira.
2. **Exposição.** Parâmetro `bairro` em `buscar_eventos` (igualdade
   normalizada; aceitar CSV multi como `_lista` do cinema), faceta
   `bairros` em `facetas_eventos()` (só bairros com evento futuro), dropdown
   no site no padrão dos `Drop` do cinema. A tool MCP ganha o parâmetro na
   descrição (herda a implementação).

Instagram continua sem bairro até o NI-16 (bairro canônico da casa) — a
faceta simplesmente não o cobre; honestidade > completude.

### 5.3 Festas & baladas × shows & festivais (NI-44)

**Coluna nova `tipo`** em `eventos` (`'festa'` | `'show'` | `NULL`),
preenchida por `enriquecer.py` (idempotente, `--so-enriquecer` recalcula —
regra pode ser recalibrada sem re-raspar). Heurística v1, conservadora, na
ordem:

1. `categoria` real com sinal forte (`shows`, `festivais` → show;
   `baladas-e-festas`, `erotico...` → festa) — lembrando que ela mente às
   vezes (NI-04): categoria sozinha só decide quando o nome não contradiz;
2. palavra com fronteira no `nome` ("festival", "show", "turnê", "tributo" →
   show; "festa", "baile", "balada", "after", "esquenta" → festa);
3. sem sinal claro → `NULL` (**sem rótulo; aparece nas duas visões** — o
   princípio do projeto é errar para o lado de não esconder festa real).

No site: **chips** "festas & baladas" / "shows & festivais" no grupo de
filtros existente (`?tipo=festa|show`; sem os dois = tudo). NÃO são abas/
rotas separadas no v1 — os filtros compostos (tipo + dia + bairro) precisam
combinar, e chip é o padrão da página. Parâmetro `tipo` em
`buscar_eventos`; semântica do filtro: `tipo = %s OR tipo IS NULL`
(o sem-rótulo nunca some). Quando o NI-05 (LLM) entrar, ele assume a coluna
e a heurística vira fallback.

Casos de calibração conhecidos: "Forró na Varanda" (show ou festa? — forró
com banda ao vivo é o limite honesto do v1: fica NULL), tributos (show),
"DEU BENZA" (festa).

### 5.4 Coleções sazonais (NI-47)

Mapa curado em `lib/colecoes.js`: `{rotulo, termos_fts, janela}` (ex.:
`{"festa junina", "junina OR arraiá OR quadrilha OR forró", jun–jul}`).
O chip só renderiza dentro da janela do ano e ao clicar preenche
`?texto=<termos_fts>` — é açúcar sobre a busca que já existe; zero backend,
zero schema. Réveillon/carnaval/halloween entram no mesmo mapa quando a
época chegar (o mapa é o produto: curadoria versionada, como a watchlist).

## 6. NI-46 — "perto de mim" (condicionada à cobertura)

**Gate de entrada:** cobertura geral de `lat` ≥ ~60% (um "perto de mim" que
ignora metade da agenda é pior que não existir; o filtro de bairro cobre o
caso enquanto isso). **Medição de 2026-07-27 (§2): 65% — passa raspando**,
com uma ressalva grande: a cobertura vem quase toda do Sympla; Ticket and Go
(75 futuros, 2ª maior fonte) manda coordenada nula. Decisão registrada:
implementar por último (ordem do §8) e **re-medir na hora** — se o mix de
fontes tiver piorado (ex.: Shotgun de volta sem lat), o item espera. Um
geocoding barato do `endereco` do Ticket and Go (CEP → coordenada) é a
alavanca óbvia se precisar subir a cobertura, mas é chamada externa — fora
desta spec, anotar no NI-46 se chegar a hora.

Se mantido o gate:

- `buscar_eventos(..., perto_lat=, perto_lon=)`: ordena por distância
  haversine em SQL (expressão direta; PostGIS é overkill para o recorte DF)
  — eventos sem `lat` vão para o fim, nunca somem. Raio máximo NÃO entra no
  v1 (ordenar já responde "perto de mim"; raio esconderia evento).
- API: `/api/dados/eventos?perto=<lat>,<lon>` (um parâmetro só, validado).
- Front: botão "perto de mim" que pede `navigator.geolocation` e recarrega a
  URL com `?perto=` — **primeiro recurso do site que exige JS**, e a
  degradação é explícita: sem JS/permissão negada, o botão simplesmente não
  faz nada além de sugerir o filtro de bairro.
- **Postura:** a coordenada do visitante desce como parâmetro, é usada na
  query e NÃO é gravada nem logada; nota na página "sobre". A precisão que o
  navegador der basta (bairro-level serve).

## 7. Mudanças por camada (resumo)

| Camada | Mudança |
|---|---|
| `sql/schema.sql` | `eventos` += `tipo` via `ADD COLUMN IF NOT EXISTS` (aditivo e idempotente — **sem drop, sem re-raspar**) |
| scrapers | **intocados** — nada aqui re-raspa |
| `src/derivar.py` | fallback textual de `bairro` a partir de `endereco` (dicionário de RAs) |
| `src/enriquecer.py` | classificação `tipo` (festa/show/NULL), idempotente |
| `src/consulta.py` | `buscar_eventos` += `bairro` (multi), `tipo`, `perto_lat/lon` (§6); `facetas_eventos()` nova (dias/bairros/tipos) |
| `api/dados.py` | traduz params novos; default de período com texto (não — ver §3: o default é do front); `facetas` na resposta de `/eventos`; `?perto=` |
| `app/festas/` | resumo no card, chip "próximos", calendário, dropdown bairro, chips tipo, chip sazonal |
| `app/evento/[id]/` | link "ver no mapa" |
| `lib/` | `config.js` += período "próximos"; `colecoes.js` novo; `Calendario` generalizado |
| MCP (`mcp_server.py`) | **sem tool nova**; `buscar_eventos` anuncia os parâmetros novos na descrição da tool |

## 8. Ordem de implementação (cada etapa entrega valor sozinha)

1. **NI-41 — busca por casa** (§3): é bug com cara de produto quebrado;
   front + teste, zero schema. *Quick win, primeiro.*
2. **NI-38 + NI-39 — card com resumo + link Maps** (§4): só front.
3. **NI-43 — calendário** (§5.1): `facetas_eventos()` (só `dias`) + API +
   front. Zero schema.
4. **NI-45 + NI-44 — bairro e tipo** (§5.2, §5.3): coluna aditiva +
   derivação/enriquecimento a seco (`--so-derivar` / `--so-enriquecer`),
   depois faceta/filtros/chips. Sem drop, sem re-raspar.
5. **NI-47 — sazonais** (§5.4): a qualquer momento, é `lib/` puro.
6. **NI-46 — perto de mim** (§6): por último, atrás do gate de cobertura.

## 9. Plano de teste

- `tests/test_enriquecer.py`: classificação `tipo` (caso categoria forte,
  caso palavra no nome, caso ambíguo → NULL; contradição categoria × nome
  → NULL) e que o filtro `tipo` não esconde os NULL.
- `tests/test_bronze.py` ou novo caso em derivação: fallback de bairro
  (endereço com RA conhecida → bairro; endereço opaco → NULL; grafia
  normalizada).
- `tests/test_api_dados.py`: busca com texto sem período devolve futuros
  (regressão do NI-41); `facetas` presente em `/eventos`; params `bairro`/
  `tipo`/`perto` traduzidos; postura preservada (organizador oculto, trecho).
- `tests/test_mcp_server.py`: parâmetros novos aceitos pela tool.
- Visual: dois temas + mobile, padrão do projeto.

## 10. Riscos e decisões registradas

- **Heurística de `tipo` erra** — mitigada pelo terceiro estado NULL (nunca
  esconde) e por viver no `enriquecer` (recalibrar = `--so-enriquecer`,
  minutos). O rótulo definitivo é do NI-05.
- **Dicionário de RAs incompleto** — bairro nulo continua sendo o
  comportamento; a faceta só mostra o que existe. Lista cresce por
  curadoria (e o NI-16 é a solução estrutural).
- **Calendário com janela longa** — ao contrário do cinema (~8 dias), a
  agenda de eventos alcança meses; o calendário precisa navegar entre meses
  (o do cinema não precisava). Ajuste no componente ao generalizar.
- **`facetas_eventos()` é mais uma query por render** — sai na MESMA
  resposta cacheada da CDN (`/api/dados/eventos`), então o custo real é ~0
  em HIT; conferir que não degrada o TTFB em MISS (liga com o NI-50).
- **Schema aditivo, sem drop** (etapa 4): `tipo` entra por `ADD COLUMN IF
  NOT EXISTS` no `schema.sql` — precedente novo no projeto; se a coluna um
  dia mudar de forma (não-aditivo), aí sim vale a convenção do drop.
- **Privacidade do `?perto=`** — decisão registrada: coordenada não é
  persistida em lugar nenhum; se um dia houver log de acesso do site, o
  parâmetro entra na lista de campos a expurgar.
