# Spec — Rework de eventos pós-beta (NI-38/39/41/43/44/45/46/47)

> **Status:** especificada em 2026-07-27, **revista em 2026-07-28** contra a
> arquitetura medalhão (`20260728_arquitetura-medalhao/`, implementada no mesmo
> dia). Aguardando implementação.
>
> **O quê/por quê:** rodada de feedback do beta (autor + vários amigos, 27/07)
> rendeu 19 pedidos, todos registrados no backlog (NI-38 a NI-54). Esta spec
> cobre SÓ a parte de eventos executável com **dado que já existe na base** —
> mesmo quando exige mudar tratamento ou modelagem. Fica de fora tudo que
> depende de raspagem nova (NI-48), de classificador LLM (NI-42, NI-49) ou que
> é transversal ao site (NI-50 a NI-54).
>
> **Contexto:** a página `/festas` tem card enxuto (sem resumo), três períodos
> fixos (hoje/fds/7d) e busca textual — e a busca por casa, que o FTS foi feito
> para atender, falha na prática no site (§3). O cinema já passou pelo rework
> equivalente (spec `20260727_rework-pagina-cinema/`); vários padrões de lá se
> reaproveitam aqui (calendário, facetas na resposta, filtros na URL).

---

## 0. O que a arquitetura medalhão mudou nesta spec (revisão de 28/07)

A spec foi escrita um dia antes da reorganização em camadas. Nada do **produto**
mudou; mudaram os endereços, um dos alicerces de dado, e — o mais importante —
apareceu uma **regra nova de desenho** que restringe onde duas destas etapas
podem morar.

**(a) A regra: uma coluna, um escritor.** O bug que motivou a arquitetura
medalhão foi `categoria` sendo escrita por dois passos legítimos, onde quem
escrevia por último ganhava (206 de 224 eventos do Sympla errados por semanas).
A lição vale para as duas colunas que esta spec cria ou preenche:

- **`bairro`** já é escrito por `comum.aplicar()` (vem das `DERIVACOES` do
  Sympla e do Zig). O fallback textual do §5.2 **não pode** virar um segundo
  escritor em `enriquecer.py`, como o rascunho previa — vai DENTRO da composição
  do evento em `comum.aplicar()`, mantendo um escritor só.
- **`tipo`** (§5.3) é escrito só pelo `enriquecer.py`. Para isso ele **NÃO PODE
  entrar em `comum.COLS_EVENTO`** — essa lista é reescrita inteira a cada
  reconstrução, e `tipo` seria zerado toda rodada. Fica ao lado de `ruido`,
  `dedupe_*` e `sumido`, que são exatamente as colunas de outros donos.

**(b) O Ticket and Go perdeu o endereço.** O rascunho contava com
`endereco_completo` textual na bronze para extrair bairro da 2ª maior fonte.
A API V1 foi desligada (NI-57) e a V2 **não expõe endereço nenhum**: hoje são
5 de 88 eventos com `endereco`, todos payloads da era antiga. O §5.2 foi
reescrito em cima disso.

**(c) O Shotgun voltou, e traz bairro de graça.** Ele estava quebrado quando a
spec foi medida (0 eventos); hoje são 68 futuros, e o `endereco` deles **é o
bairro** ("Asa Sul", "Saan", "São Jorge" — o `addressLocality` do JSON-LD).
Isso torna metade do §5.2 uma linha de código, não um dicionário.

**(d) `categoria` de Shotgun e Ticket and Go virou NULL.** As duas gravavam
constante (`"MusicEvent"` 65/65 e `"Evento"` 71/72) e saíram pelo mesmo
argumento que derrubou o `event_type`='NORMAL'. Consequência direta para o
§5.3: o sinal `categoria` agora existe **só no Sympla**.

**(e) Endereços novos.** `src/derivar.py` não existe mais (dissolveu-se nas
trilhas de `src/tratamento/`); `sql/schema.sql` virou um arquivo por tabela; as
tabelas moram em schemas (`tratado.eventos`, e a consulta lê as views de
`public`). O §7 já está atualizado.

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

Medido na base de produção em **2026-07-28**, depois da rodada completa
pós-medalhão (379 eventos futuros visíveis — sem ruído/sumido/cancelado, só
canônicos). A medição de 27/07 fica preservada no `git log` para comparação.

| fonte | futuros | com lat | com bairro | com descrição | com endereço | com categoria |
|---|---|---|---|---|---|---|
| sympla | 193 | 193 (100%) | 86 (45%) | 177 (92%) | 180 (93%) | 187 (97%) |
| ticketandgo | 75 | **0** | 0 | 75 (100%) | **5 (7%)** | 1 |
| shotgun | 68 | 68 (100%) | **0** | 68 (100%) | **68 (100%)** | 0 |
| instagram | 37 | 0 | 0 | 37 (100%) | 0 | 0 |
| ingresse | 4 | 4 (100%) | 0 | 4 (100%) | 0 | 0 |
| zig | 2 | 0 | 2 | 2 | 2 | 0 |
| **total** | **379** | **265 (69%)** | **88 (23%)** | **363 (95%)** | **250 (65%)** | **188 (49%)** |

O que mudou desde 27/07 e importa para o plano:

- **`lat` subiu de 65% para 69%** — o Shotgun voltou com 100% de coordenada, o
  que reforça o gate do §6 em vez de enfraquecê-lo.
- **`bairro` caiu de 30% para 23%**, e a queda é boa notícia disfarçada: o
  denominador cresceu (285 → 379) porque o Shotgun voltou, e ele tem 0 de
  `bairro` **com 100% de `endereco`**. É o caso mais fácil do §5.2.
- **`endereco` do Ticket and Go despencou para 7%** (era a matéria-prima da
  extração textual planejada). A fonte parou de expor endereço; não é bug a
  consertar.
- **`categoria` só é confiável no Sympla** (187 dos 188 do total). Ver §0d.

| Precisa de | Já existe? | Onde |
|---|---|---|
| Resumo do evento | **SIM** | `descricao` — a listagem da API já devolve trecho de 600 chars (`api/dados.py DESCRICAO_SITE`); o card simplesmente não usa |
| Endereço p/ Maps | SIM | `endereco`, `local_nome`, `cidade`; `lat`/`lon` normalizados por Sympla, Ingresse e Shotgun (Zig e Ticket and Go mandam nulo) |
| Bairro | PARCIAL | `tratamento/sympla.py` e `tratamento/zig.py` derivam do payload; **o `endereco` do Shotgun É o bairro** e só falta copiá-lo; o Sympla tem endereço textual em 93% para o dicionário de RAs; Ticket and Go e Instagram ficam nulos |
| Dias com evento (calendário) | derivável | `start_date` (ISO UTC, comparação lexical) → dia local, mesmo desenho de `facetas_filmes()["dias"]` |
| Tipo festa × show | derivável | `nome`, `descricao`, `atracoes` — e `categoria`, que agora só o Sympla preenche |
| Busca por casa | **SIM** | o FTS indexa `local_nome`/`organizador` desde a v1.1 — o problema é outro (§3) |
| Calendário (UI) | SIM | `app/filmes/Calendario.jsx` (NI-35), a generalizar |

Conclusão que molda a spec, e que a revisão não mudou: **quase tudo é exposição
de dado que já existe** (front + parâmetro de consulta + faceta). A única
mudança de schema é a coluna `tipo` (§5.3), aditiva: um
`ALTER TABLE tratado.eventos ADD COLUMN IF NOT EXISTS tipo TEXT` **ao lado** da
definição em `sql/tratado/eventos.sql` — dentro do `CREATE TABLE` não basta, que
ele não altera tabela existente. Idempotente, aplicado sozinho pelo
`conectar(aplicar_schema=True)`. `tipo` e `bairro` são preenchidos a seco
(`--so-enriquecer` / `--so-derivar`), sem re-raspar.

## 3. NI-41 — a busca por casa que "deu erro"

**Diagnóstico CONFIRMADO na base real (2026-07-27; o default segue igual em
28/07):** não é o FTS — é a interação busca × período. Medido:
`websearch_to_tsquery('pt', 'Ordinário')` vira `'ordinari'` e casa com TODOS os
~40 eventos da casa na base (`local_nome = "Ordinário Bar & Música"`,
majoritariamente canônicos, `ruido=0`, `sumido=0`); a conciliação
Instagram↔plataforma está íntegra. O que quebra é o front:
`app/festas/page.jsx:69` faz `const periodo = sp?.periodo ?? 'hoje'` — quem
digita "Ordinário" busca a agenda da casa, mas o site responde "a agenda da casa
HOJE". No dia do teste, o único evento do dia (Segunda da Resenha, 00h local) já
tinha começado quando a busca rodou (`data_inicio = agora`) → zero resultados,
com cara de busca quebrada. O texto do vazio ainda sugere "amplie o período" — o
sistema sabe o que aconteceu e mesmo assim erra o default.

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

Cobertura favorável: **95% dos futuros têm descrição** (§2), e as duas fontes
que mais cresceram desde o rascunho (Shotgun e Instagram) estão em 100%.

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

O fallback textual carrega o grosso do Ticket and Go e do Instagram, que juntos
são 112 dos 379 futuros e não têm coordenada nem endereço — para eles a query
vira `local_nome, Brasília`, que é o que a casa tem de identificável. Pior que
coordenada, melhor que nada.

## 5. Filtros novos na `/festas`

Filosofia inalterada (spec do site): filtros **vivem na URL**, funcionam sem
JS, SSR. Parâmetro novo entra em `servico/consulta.buscar_eventos()` (nunca
lógica na API), a `api/dados.py` só traduz querystring, o MCP herda de graça.

### 5.1 Calendário de data (NI-43)

- **Faceta:** `facetas_eventos()` nova em `servico/consulta.py` devolvendo
  `{"dias": [...], "bairros": [...], "tipos": [...]}` — calculada só sobre
  evento futuro visível (mesmos filtros default da busca: sem ruído, sem
  sumido, sem cancelado, só canônico), lendo `public.eventos` como o resto da
  camada de consulta. `dias` = dia **LOCAL simples** de Brasília do
  `start_date` (`to_char(... AT TIME ZONE 'America/Sao_Paulo', 'YYYY-MM-DD')`).
  **Decisão do corte:** o dia do calendário é o dia local SIMPLES
  (00:00–24:00), consistente com o agrupamento visível da lista
  (`agruparPorDia`/`chaveDia`, que não desloca 6h) — uma festa de sábado 1h
  aparece agrupada em "sábado" na tela, então o dia "sábado" do calendário
  tem que trazê-la. O corte das 6h continua valendo onde sempre valeu: nos
  atalhos de período (`_janela`) e nos rótulos "hoje/amanhã".
- **API:** a resposta de `/api/dados/eventos` ganha o campo `facetas` (mesmo
  padrão do `/filmes`: junto na resposta, sem round-trip extra).
- **Front:** generalizar `app/filmes/Calendario.jsx` para receber a rota-base e
  os dias habilitados; dia sem evento fica desabilitado. Selecionar dia escreve
  `?de=YYYY-MM-DDT00:00:00-03:00&ate=YYYY-MM-DDT23:59:59-03:00` (a API já
  aceita `de/ate`; nenhum parâmetro novo). Faixa de datas (de–até em dois
  cliques) fica para um passo 2, se o dia único se provar curto.

### 5.2 Filtro por bairro (NI-45)

Reescrito na revisão de 28/07: o Shotgun voltou trazendo o dado quase pronto, e
o Ticket and Go perdeu a matéria-prima que o rascunho pressupunha (§0b, §0c).
São **três** partes agora, em ordem de retorno por esforço.

1. **Shotgun: uma linha, +68 eventos.** O `addressLocality` do JSON-LD é o
   bairro (medido: "Asa Sul", "Saan", "São Jorge") e hoje ele já vai para
   `endereco` — falta só mapeá-lo também para `bairro` em
   `tratamento/shotgun.py:normalizar`. Sozinho isso leva a cobertura de 23%
   para ~41%. É a melhor razão custo/benefício da spec inteira.
2. **Dicionário textual, dentro do ÚNICO escritor da coluna.** Para quem tem
   `endereco` mas não `bairro` (o Sympla, com 93% de endereço e 45% de
   bairro), extrair por dicionário das RAs/regiões de Brasília (Asa Sul, Asa
   Norte, Taguatinga, Águas Claras, Sudoeste, Lago Sul/Norte, Ceilândia,
   Guará, Setores SCES/SCLS/SHIS…) — lista curada em `tratamento/bairros.py`,
   módulo novo, com `extrair(endereco) -> str | None`.
   **Onde ele roda é decisão de arquitetura, não de gosto:** dentro da
   composição do evento em `comum.aplicar()`, como último passo, *depois* das
   `DERIVACOES` da fonte e só quando `bairro` saiu nulo. Não em
   `enriquecer.py`, como dizia o rascunho — ali `bairro` ganharia um segundo
   escritor, que é exatamente o desenho que produziu o bug da `categoria`
   (§0a). Conservador como sempre: sem casamento claro, fica nulo. Normalização
   de grafia junto (unaccent + caixa) para a faceta não listar "ASA NORTE" e
   "Asa Norte" como dois bairros. É derivação a seco — `--so-derivar`
   reprocessa a base inteira.
   Amostra real do que ele enfrenta no Sympla: `"Pistão Sul"`, `"SRES"`,
   `"Eixo Monumental"`, `"Núcleo Rural Jardim II"`, `"St. Oeste Colonia
   Colonia Agricola Cabeceira Vale, 3"` — dá para acertar boa parte, e a parte
   opaca é para ficar nula mesmo.
3. **Exposição.** Parâmetro `bairro` em `buscar_eventos` (igualdade
   normalizada; aceitar CSV multi como `_lista` do cinema), faceta
   `bairros` em `facetas_eventos()` (só bairros com evento futuro), dropdown
   no site no padrão dos `Drop` do cinema. A tool MCP ganha o parâmetro na
   descrição (herda a implementação).

**Teto honesto:** Ticket and Go (75 futuros) e Instagram (37) não têm endereço
nenhum — 112 dos 379 futuros ficam fora do filtro por construção, e nenhum
dicionário resolve isso. O caminho estrutural para eles é o NI-16 (bairro
canônico da casa), e ele ficou viável agora: a camada `curado` existe desde a
fatia 6 do medalhão, com `curado.locais` já servindo de referência de casas.
Hoje essa é a alavanca mais promissora do item, não o dicionário. Honestidade >
completude: a faceta lista o que existe.

### 5.3 Festas & baladas × shows & festivais (NI-44)

**Coluna nova `tipo`** em `tratado.eventos` (`'festa'` | `'show'` | `NULL`),
preenchida por `tratamento/enriquecer.py` (idempotente, `--so-enriquecer`
recalcula — regra pode ser recalibrada sem re-raspar).

> ⚠️ **`tipo` NÃO entra em `comum.COLS_EVENTO`.** Essa lista é reescrita
> inteira a cada reconstrução da prata; `tipo` seria zerado toda rodada. Ele
> pertence ao grupo de `ruido`/`dedupe_*`/`sumido` — colunas de `tratado` cujo
> dono é outro passo do tratamento. Ver §0a.

Heurística v1, conservadora, na ordem:

1. `categoria` com sinal forte (`shows`, `festivais` → show; `baladas-e-festas`,
   `erotico…` → festa). **Só o Sympla preenche `categoria` desde 28/07** — as
   constantes do Shotgun e do Ticket and Go saíram (§0d). Na prática este passo
   alcança ~187 dos 379 futuros, e ela ainda mente às vezes (NI-04): categoria
   sozinha só decide quando o nome não contradiz;
2. palavra com fronteira no `nome` ("festival", "show", "turnê", "tributo" →
   show; "festa", "baile", "balada", "after", "esquenta" → festa) — é o passo
   que carrega Shotgun, Ticket and Go e Instagram, ou seja, metade da agenda;
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
caso enquanto isso).

**Medição de 2026-07-28 (§2): 69% — passa, e passa melhor que em 27/07 (65%).**
O Shotgun voltando com 100% de coordenada foi o que subiu a régua. A ressalva
grande continua: a cobertura vem de Sympla + Shotgun; **Ticket and Go (75
futuros, 2ª maior fonte) e Instagram (37) mandam coordenada nula** — 112 eventos
que a ordenação vai empurrar para o fim. Decisão registrada: implementar por
último (ordem do §8) e **re-medir na hora**. Um geocoding barato do `endereco`
do Ticket and Go era a alavanca óbvia, mas a fonte parou de expor endereço
(§0b), então essa porta fechou — o que sobra é o NI-16 (coordenada canônica da
casa em `curado.locais`), a mesma alavanca do §5.2.

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

Atualizado para a estrutura pós-medalhão.

| Camada | Mudança |
|---|---|
| `sql/tratado/eventos.sql` | `+= tipo` via `ADD COLUMN IF NOT EXISTS` **ao lado** da definição (aditivo e idempotente — sem drop, sem re-raspar) |
| `src/coleta/` | **intocado** — nada aqui re-raspa |
| `src/tratamento/shotgun.py` | `normalizar` passa a mapear o `addressLocality` também para `bairro` (§5.2.1) |
| `src/tratamento/bairros.py` | **novo** — dicionário de RAs + `extrair(endereco)` |
| `src/tratamento/comum.py` | chama `bairros.extrair` como último passo da composição, só quando `bairro` saiu nulo (mantém UM escritor da coluna) |
| `src/tratamento/enriquecer.py` | classificação `tipo` (festa/show/NULL), idempotente; **`tipo` fora de `COLS_EVENTO`** |
| `src/servico/consulta.py` | `buscar_eventos` += `bairro` (multi), `tipo`, `perto_lat/lon` (§6); `facetas_eventos()` nova (dias/bairros/tipos) |
| `api/dados.py` | traduz params novos; `facetas` na resposta de `/eventos`; `?perto=` |
| `app/festas/` | resumo no card, chip "próximos", calendário, dropdown bairro, chips tipo, chip sazonal |
| `app/evento/[id]/` | link "ver no mapa" |
| `lib/` | `config.js` += período "próximos"; `colecoes.js` novo; `Calendario` generalizado |
| MCP (`src/servico/mcp_server.py`) | **sem tool nova**; `buscar_eventos` anuncia os parâmetros novos na descrição da tool |

## 8. Ordem de implementação (cada etapa entrega valor sozinha)

1. **NI-41 — busca por casa** (§3): é bug com cara de produto quebrado;
   front + teste, zero schema. *Quick win, primeiro.*
2. **NI-38 + NI-39 — card com resumo + link Maps** (§4): só front.
3. **NI-45a — bairro do Shotgun** (§5.2.1): uma linha em
   `tratamento/shotgun.py` + `--so-derivar`. Leva a cobertura de 23% para
   ~41% e não depende de mais nada. *Etapa nova na revisão de 28/07 — antes
   estava embutida no bloco de bairro, e não dava para ver que era barata.*
4. **NI-43 — calendário** (§5.1): `facetas_eventos()` (só `dias`) + API +
   front. Zero schema.
5. **NI-45b + NI-44 — dicionário de bairro e tipo** (§5.2.2, §5.3): coluna
   aditiva + derivação/enriquecimento a seco (`--so-derivar` /
   `--so-enriquecer`), depois faceta/filtros/chips. Sem drop, sem re-raspar.
6. **NI-47 — sazonais** (§5.4): a qualquer momento, é `lib/` puro.
7. **NI-46 — perto de mim** (§6): por último, atrás do gate de cobertura.

## 9. Plano de teste

- `tests/test_enriquecer.py`: classificação `tipo` (caso categoria forte,
  caso palavra no nome, caso ambíguo → NULL; contradição categoria × nome
  → NULL) e que o filtro `tipo` não esconde os NULL. **E o caso que a
  arquitetura nova exige: uma reconstrução completa (`comum.aplicar`) NÃO pode
  zerar `tipo`** — é o teste que pega o dia em que alguém puser a coluna em
  `COLS_EVENTO`.
- `tests/test_bronze.py`: bairro do Shotgun sai do payload; fallback textual
  (endereço com RA conhecida → bairro; endereço opaco → NULL; grafia
  normalizada). O teste de FRONTEIRA já existente passa a cobrir as duas
  colunas novas de graça, porque compara `COLS_EVENTO` inteira.
- `tests/test_api_dados.py`: busca com texto sem período devolve futuros
  (regressão do NI-41); `facetas` presente em `/eventos`; params `bairro`/
  `tipo`/`perto` traduzidos; postura preservada (organizador oculto, trecho).
- `tests/test_mcp_server.py`: parâmetros novos aceitos pela tool.
- Visual: dois temas + mobile, padrão do projeto.

## 10. Riscos e decisões registradas

- **Heurística de `tipo` erra** — mitigada pelo terceiro estado NULL (nunca
  esconde) e por viver no `enriquecer` (recalibrar = `--so-enriquecer`,
  minutos). O rótulo definitivo é do NI-05. **Risco novo desde 28/07:** com
  `categoria` restrita ao Sympla, o passo 2 (palavra no nome) carrega metade da
  agenda sozinho — calibrar contra Shotgun e Ticket and Go, não só contra o
  Sympla, senão a regra fica boa onde já havia sinal e ruim onde não havia.
- **Dicionário de RAs incompleto** — bairro nulo continua sendo o
  comportamento; a faceta só mostra o que existe. Lista cresce por
  curadoria (e o NI-16 é a solução estrutural — hoje viável, porque a camada
  `curado` existe).
- **Duas fontes fora do filtro de bairro e do "perto de mim"** (Ticket and Go e
  Instagram, 112 de 379 futuros) — e a porta do geocoding fechou junto com o
  endereço da V1. Aceito: os dois são *afunilamento opcional*, nunca o caminho
  padrão da página. Nenhum deles pode virar filtro default.
- **Calendário com janela longa** — ao contrário do cinema (~8 dias), a
  agenda de eventos alcança meses; o calendário precisa navegar entre meses
  (o do cinema não precisava). Ajuste no componente ao generalizar.
- **`facetas_eventos()` é mais uma query por render** — sai na MESMA
  resposta cacheada da CDN (`/api/dados/eventos`), então o custo real é ~0
  em HIT; conferir que não degrada o TTFB em MISS (liga com o NI-50).
- **Schema aditivo, sem drop** (etapa 5): `tipo` entra por `ADD COLUMN IF NOT
  EXISTS` em `sql/tratado/eventos.sql`; mudança não-aditiva segue a regra (b)
  da convenção (dropar só derivadas), e desde a fatia 7 do medalhão `tratado`
  inteira é reconstruível — o que torna a regra (b) barata pela primeira vez.
- **Privacidade do `?perto=`** — decisão registrada: coordenada não é
  persistida em lugar nenhum; se um dia houver log de acesso do site, o
  parâmetro entra na lista de campos a expurgar.
- **Um escritor por coluna** (§0a) — é a decisão de desenho que a revisão de
  28/07 acrescentou, e a que mais muda código em relação ao rascunho. Vale
  para tudo que esta spec escrever em `tratado.eventos` daqui para frente.
