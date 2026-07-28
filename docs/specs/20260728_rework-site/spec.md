# Spec — Rework do site pós-beta (NI-38/39/41/43/44/45/46/47 + NI-50/51/52/53)

> **Status: IMPLEMENTADA em 2026-07-28.** Especificada em 27/07, revista duas
> vezes em 28/07 (contra a arquitetura medalhão e contra o código do site — a
> segunda renomeou a pasta, que era `20260728_rework-eventos`, e ampliou o
> escopo para os itens transversais de usabilidade), executada nas nove etapas
> do §11 no mesmo dia. **O que a execução mediu, corrigiu e deixou de fora está
> na §14** — leia-a antes desta spec, porque ela desmente três previsões daqui.
>
> **O quê/por quê:** rodada de feedback do beta (autor + vários amigos, 27/07)
> rendeu 19 pedidos, todos registrados no backlog (NI-38 a NI-54). Esta spec
> cobre a parte executável com **dado que já existe na base** — mesmo quando
> exige mudar tratamento ou modelagem — **mais os itens de usabilidade do site
> que não dependem de dado nenhum** (feedback, agenda, compartilhar,
> velocidade). Fica de fora tudo que depende de raspagem nova (NI-48) ou de
> classificador LLM (NI-42, NI-49).
>
> **Contexto:** a página `/festas` tem card enxuto (sem resumo), três períodos
> fixos (hoje/fds/7d) e busca textual — e a busca por casa, que o FTS foi feito
> para atender, falha na prática no site (§3). O cinema já passou pelo rework
> equivalente (spec `20260727_rework-pagina-cinema/`); vários padrões de lá se
> reaproveitam aqui (calendário, facetas na resposta, filtros na URL).

---

## 0. Duas revisões antes de executar

A spec foi escrita em 27/07 e revista duas vezes em 28/07: primeiro contra a
reorganização em camadas, depois contra o código do site que ela pretende
mudar. As duas revisões corrigiram premissas do rascunho — e a segunda achou um
item do backlog que **já estava implementado**.

### 0.1 O que a arquitetura medalhão mudou (revisão de 28/07, manhã)

Nada do **produto** mudou; mudaram os endereços, um dos alicerces de dado, e — o
mais importante — apareceu uma **regra nova de desenho** que restringe onde duas
destas etapas podem morar.

**(a) A regra: uma coluna, um escritor.** O bug que motivou a arquitetura
medalhão foi `categoria` sendo escrita por dois passos legítimos, onde quem
escrevia por último ganhava (206 de 224 eventos do Sympla errados por semanas).
A lição vale para as duas colunas que esta spec cria ou preenche:

- **`bairro`** já é escrito por `comum.aplicar()` (vem das `DERIVACOES` do
  Sympla e do Zig). O fallback textual do §5.2 **não pode** virar um segundo
  escritor em `enriquecer.py`, como o rascunho previa — vai DENTRO da composição
  do evento em `comum.aplicar()`, mantendo um escritor só. (A `curadoria.py`
  também sobrescreve `bairro`, mas ela é a camada humana que roda por último,
  por desenho: correção de pessoa vence derivação, e isso não é disputa.)
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
`public`). O §10 já está atualizado.

### 0.2 O que a leitura do código do site mudou (revisão de 28/07, tarde)

Cinco achados, todos verificados no repositório, não deduzidos:

**(f) O NI-54 JÁ ESTÁ IMPLEMENTADO — e o backlog afirma o contrário.** O item
diz "hoje NÃO existe analytics nenhum instalado" e propõe `@vercel/analytics`.
A realidade, desde o commit `d796a90`: **PostHog** (`posthog-js` no
`package.json`, `instrumentation-client.js` com `capture_pageview`,
`capture_pageleave` e `capture_exceptions`), servido pelo **próprio domínio**
via rewrites `/ph/*` no `next.config.mjs` — a defesa contra adblock, que o
comentário de lá registra como obrigatória desde o início, porque retrofitar
invalida a série histórica. As envs `NEXT_PUBLIC_POSTHOG_KEY`/`_HOST` existem
**só em Production**, o que resolve local × prod de graça. Quatro eventos custom
já capturam: `ticket_link_clicked`, `other_platform_link_clicked`,
`film_session_clicked`, `event_search_performed`.
Consequências: o NI-54 sai do backlog; o **NI-53 está destravado** (ele
dependia de existir analytics para o UTM ser lido por alguém); o NI-50 tem com
o que ser medido; e cada elemento novo desta spec nasce instrumentado (§9).

**(g) `api/dados.py` é GET-only.** A classe `handler` implementa `do_GET` e
nada mais. O botão de feedback (§7) não é "só front": exige um `do_POST` — a
primeira ESCRITA que o site faz na base, num arquivo cuja docstring diz, com
razão, que ele "não tem lógica própria". A fronteira é preservada do mesmo
jeito de sempre: a API traduz o formulário, quem escreve é uma função da camada
de serviço.

**(h) O `Calendario.jsx` já resolve o problema que o §13 dava como aberto.**
O risco registrado dizia "a agenda de eventos alcança meses; o calendário
precisa navegar entre meses (o do cinema não precisava)". Lendo o componente:
ele deriva `meses` da própria lista de `dias` e **renderiza um bloco por mês**.
Não falta navegação — falta decidir se empilhar N meses é a UI certa (§5.1). E
ele já recebe `hrefDia` pronto do pai, então também **não precisa receber a
"rota-base"** que o rascunho previa: a generalização é MOVER o arquivo, não
mudar a API dele.

**(i) O filtro `gratis` mora na `api/dados.py`, não na `consulta.py`.** É uma
list comprehension aplicada DEPOIS da busca (`evs = [e for e in evs if
e.get("tem_gratis") == 1]`), com um comentário assumindo o desvio. É a única
exceção existente à regra "a API não tem lógica" que esta spec reafirma no §5 —
e ela vira dívida visível quando `bairro` e `tipo` entrarem pelo caminho certo,
ao lado dela. Pior: por rodar depois do `limite`, ela filtra os N já buscados em
vez da base (§5.5). Decisão: **migrar o `gratis` para `buscar_eventos` junto**.

**(j) Não existe nenhum `loading.jsx` no `app/`.** Toda navegação por filtro
espera o SSR sem nenhum sinal de vida na tela — que é exatamente a queixa do
NI-50 ("parece que tá re-puxando da base toda vez"). É a alavanca mais barata
do item (§8).

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
| botão de feedback (bug/sugestão/"quero minha casa") | NI-52 | **sim** (§7) — a única peça sem alicerce pronto |
| adicionar ao Google Agenda | NI-51 | **sim** (§4.3) — link de template, sem API nem auth |
| botão de compartilhar com UTM | NI-53 | **sim** (§4.4) — destravado pelo achado (f) |
| velocidade ao trocar filtro | NI-50 | **sim** (§8) — e vira pré-condição dos filtros novos |
| instrumentar o site | NI-54 | **já implementado** (§0.2f) — sai do backlog; §9 herda |
| expandir o card no clique | NI-40 | não — prioridade baixa do autor, checar UX antes |
| título limpo na derivação | NI-33 | não — é dívida de DADO, não de site |
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
- **`categoria` só é confiável no Sympla** (187 dos 188 do total). Ver §0.1d.

| Precisa de | Já existe? | Onde |
|---|---|---|
| Resumo do evento | **SIM** | `descricao` — a listagem da API já devolve trecho de 600 chars (`api/dados.py DESCRICAO_SITE`); o card simplesmente não usa |
| Endereço p/ Maps | SIM | `endereco`, `local_nome`, `cidade`; `lat`/`lon` normalizados por Sympla, Ingresse e Shotgun (Zig e Ticket and Go mandam nulo) — mas ainda **fora de `consulta.CAMPOS`** (§4.2) |
| Bairro | PARCIAL | `tratamento/sympla.py` e `tratamento/zig.py` derivam do payload; **o `endereco` do Shotgun É o bairro** e só falta copiá-lo; o Sympla tem endereço textual em 93% para o dicionário de RAs; Ticket and Go e Instagram ficam nulos |
| Dias com evento (calendário) | derivável | `start_date` (ISO UTC, comparação lexical) → dia local, mesmo desenho de `facetas_filmes()["dias"]` |
| Tipo festa × show | derivável | `nome`, `descricao`, `atracoes` — e `categoria`, que agora só o Sympla preenche |
| Busca por casa | **SIM** | o FTS indexa `local_nome`/`organizador` desde a v1.1 — o problema é outro (§3) |
| Calendário (UI) | SIM | `app/filmes/Calendario.jsx` (NI-35) — a MOVER, não a reescrever (§0.2h) |
| Dropdown de filtro (UI) | SIM | `app/filmes/Drop.jsx` + `DropFiltro.jsx` — mesmo caso: mover |
| Analytics p/ medir o efeito | **SIM** | PostHog com proxy próprio + 4 eventos custom (§0.2f) |
| Data/hora p/ o Google Agenda | SIM | `start_date`/`end_date` em ISO UTC (invariante do schema) |
| Canal de feedback | **NÃO** | é a única peça desta spec sem nenhum alicerce pronto (§7) |

Conclusão que molda a spec, e que as revisões não mudaram: **quase tudo é
exposição de dado que já existe** (front + parâmetro de consulta + faceta). As
mudanças de schema são duas, ambas ADITIVAS: a coluna `tipo` (§5.3) e a tabela
`uso.feedback` (§7). Nenhum drop, nenhuma re-raspagem: `tipo` e `bairro` se
preenchem a seco (`--so-enriquecer` / `--so-derivar`).

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
3. **Ajuste no `SearchForm`, que hoje colabora com o bug e vai colaborar com a
   correção — mas só se mexerem nele.** Ele emite
   `{periodo !== 'hoje' && <input type="hidden" name="periodo" …>}`: buscar a
   partir do estado "hoje" produz URL SEM `?periodo=`, que é exatamente o
   gatilho da regra 1 (bom). Ao acrescentar o chip "próximos", a condição de
   omissão tem que virar "omite quando o período é o default DA BUSCA", senão
   quem já está em "próximos" e digita um termo volta a uma URL ambígua. É uma
   linha, e é o tipo de detalhe que passa despercebido e reabre o bug.
4. ~~Verificação de FTS~~ **já feita no diagnóstico** (acima): o FTS casa;
   nenhuma correção de busca/dedupe necessária. Se um caso análogo aparecer
   em outra casa, o roteiro de diagnóstico é: tsquery → flags do evento →
   default de período.

Teste de regressão em `tests/test_api_dados.py`: busca com texto e sem
período devolve evento de daqui a N dias.

## 4. Card e detalhe (NI-38, NI-39, NI-51, NI-53)

### 4.1 Resumo no card (NI-38)

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

### 4.2 Link "ver no mapa" (NI-39)

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

**Pré-requisito que a leitura do código expôs:** `lat`/`lon` **não estão em
`consulta.CAMPOS`** — nem a busca nem o detalhe os devolvem hoje. Acrescentá-los
é uma linha, e serve aqui e no §6. Não há questão de postura: coordenada de
local público não é dado pessoal (diferente do `organizador`, que segue oculto).

### 4.3 "Adicionar ao Google Agenda" (NI-51)

Link de template, sem API, sem auth, sem chave — o mesmo espírito do §4.2:

    https://calendar.google.com/calendar/render?action=TEMPLATE
      &text=<título limpo>
      &dates=<AAAAMMDDTHHMMSSZ>/<AAAAMMDDTHHMMSSZ>
      &location=<local_nome, endereco>
      &details=<link da NOSSA página do evento>

Três decisões que o formato força:

- **O formato é UTC compacto**, e `start_date` já é ISO UTC por invariante do
  schema — a conversão é remover `-`, `:` e os segundos fracionários. Uma
  função em `lib/formato.js`, ao lado das outras (que hoje formatam para o fuso
  de Brasília; esta é a única que quer UTC mesmo).
- **`end_date` é a armadilha conhecida** ("às vezes vem inconsistente na
  origem" — o CLAUDE.md manda filtrar por `start_date`). Regra: usa-se
  `end_date` quando ele existe E está entre `start_date` e `start_date + 12h`;
  caso contrário, **início + 4h**. Um evento de 3 anos de duração no calendário
  de alguém é pior que uma estimativa errada por uma hora.
- **`details` leva o link da NOSSA página**, não o da fonte. Não é preferência
  de tráfego: a régua de atribuição do projeto é que o CTA de compra leva à
  fonte (e leva, no mesmo bloco); o compromisso do calendário é com quem vai ao
  evento, e a nossa página é a que reúne as plataformas e sobrevive à mudança
  de link da fonte.

`.ics` genérico (Apple/Outlook) fica **fora do v1**: é o mesmo dado, mas exige
uma rota que gere arquivo, e o Google cobre a maioria do público-alvo. Reavaliar
com número do PostHog (§9) — se o clique aparecer, a demanda existe.

### 4.4 Compartilhar (NI-53)

Botão no detalhe do evento, **client component** (é o terceiro recurso do site
que exige JS, depois do `<Tema>` e dos handlers de PostHog):

- `navigator.share` quando existe (mobile) → sheet nativo;
- fallback `navigator.clipboard.writeText` + confirmação visual ("link
  copiado");
- sem JS: o botão não aparece — a URL da página já é compartilhável por design,
  que é o fallback real.

O link compartilhado leva `?utm_source=share`. Isso só tem valor porque o
PostHog existe (§0.2f) e já captura UTM no pageview automático — era exatamente
a dependência que travava o item no backlog. Evento próprio: `share_clicked`
com `method` (`native` | `clipboard`).

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
- **Front:** **mover** `Calendario.jsx`, `Drop.jsx` e `DropFiltro.jsx` de
  `app/filmes/` para o nível compartilhado (`app/`), e importar dos dois lados.
  Contra o que o rascunho dizia, **a API do componente não muda** (§0.2h): ele
  já recebe `dias` + `selecionado` + `hrefDia`, e já renderiza um bloco por mês
  presente em `dias`. Dia sem evento fica desabilitado, como no cinema.
  Selecionar dia escreve
  `?de=YYYY-MM-DDT00:00:00-03:00&ate=YYYY-MM-DDT23:59:59-03:00`
  (a API já aceita `de/ate`; nenhum parâmetro novo).
- **O que de fato precisa de decisão** é a altura: a grade de cinema cobre ~8
  dias, a de eventos alcança meses, e empilhar 4 blocos de mês dentro de um
  `<Drop>` é uma lista de rolagem, não um calendário. Regra do v1: renderizar
  **no máximo 3 meses** a partir do mês corrente e, havendo dia habilitado além
  disso, uma linha "+ N dias depois de <mês>" que leva ao período aberto. Faixa
  de datas (de–até em dois cliques) fica para um passo 2.
- **Mover componente é o risco de regressão desta etapa**, porque mexe na
  página de cinema, que está pronta e não está em revisão. Conferir `/filmes`
  (calendário, os quatro dropdowns e o "limpar") logo depois do move, não no
  fim de tudo.

### 5.2 Filtro por bairro (NI-45)

Reescrito na revisão de 28/07: o Shotgun voltou trazendo o dado quase pronto, e
o Ticket and Go perdeu a matéria-prima que o rascunho pressupunha (§0.1b,
§0.1c). São **três** partes, em ordem de retorno por esforço.

1. **Shotgun: uma linha, +68 eventos.** Confirmado no código:
   `tratamento/shotgun.py:49` já faz `"endereco": bairro or
   addr.get("streetAddress")`, com `bairro = addr.get("addressLocality")` na
   linha 40 — o valor está na mão, só não é devolvido como `bairro`. Sozinho
   isso leva a cobertura de 23% para ~41%. É a melhor razão custo/benefício da
   spec inteira.
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
   (§0.1a). Conservador como sempre: sem casamento claro, fica nulo.
   Normalização de grafia junto (unaccent + caixa) para a faceta não listar
   "ASA NORTE" e "Asa Norte" como dois bairros. É derivação a seco —
   `--so-derivar` reprocessa a base inteira.
   Amostra real do que ele enfrenta no Sympla: `"Pistão Sul"`, `"SRES"`,
   `"Eixo Monumental"`, `"Núcleo Rural Jardim II"`, `"St. Oeste Colonia
   Colonia Agricola Cabeceira Vale, 3"` — dá para acertar boa parte, e a parte
   opaca é para ficar nula mesmo.
3. **Exposição.** Parâmetro `bairro` em `buscar_eventos` (igualdade
   normalizada; aceitar CSV multi como `_lista` do cinema), faceta
   `bairros` em `facetas_eventos()` (só bairros com evento futuro), dropdown
   no site no padrão dos `DropFiltro` do cinema. A tool MCP ganha o parâmetro
   na descrição (herda a implementação).

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
> dono é outro passo do tratamento. Ver §0.1a.

Heurística v1, conservadora, na ordem:

1. `categoria` com sinal forte (`shows`, `festivais` → show; `baladas-e-festas`,
   `erotico…` → festa). **Só o Sympla preenche `categoria` desde 28/07** — as
   constantes do Shotgun e do Ticket and Go saíram (§0.1d). Na prática este
   passo alcança ~187 dos 379 futuros, e ela ainda mente às vezes (NI-04):
   categoria sozinha só decide quando o nome não contradiz;
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

### 5.5 Dívida adjacente: o filtro `gratis` volta para a consulta

Achado (i) do §0.2. Hoje `?gratis=1` é resolvido por list comprehension na
`api/dados.py`, **depois** da consulta — o que significa que ele filtra os N
resultados já limitados, e não a base: pedir "só grátis" com `limite=60`
devolve os grátis que couberem nos 60 primeiros, não os 60 primeiros grátis.
É um bug de resultado, não só de arquitetura.

Correção: parâmetro `gratis` em `buscar_eventos` (`tem_gratis = 1` no WHERE), e
a API volta a só traduzir. Entra junto com `bairro`/`tipo` porque é a mesma
função, o mesmo teste e o mesmo commit — separá-lo seria mexer duas vezes no
mesmo lugar.

## 6. NI-46 — "perto de mim" (condicionada à cobertura)

**Gate de entrada:** cobertura geral de `lat` ≥ ~60% (um "perto de mim" que
ignora metade da agenda é pior que não existir; o filtro de bairro cobre o
caso enquanto isso).

**Medição de 2026-07-28 (§2): 69% — passa, e passa melhor que em 27/07 (65%).**
O Shotgun voltando com 100% de coordenada foi o que subiu a régua. A ressalva
grande continua: a cobertura vem de Sympla + Shotgun; **Ticket and Go (75
futuros, 2ª maior fonte) e Instagram (37) mandam coordenada nula** — 112 eventos
que a ordenação vai empurrar para o fim. Decisão registrada: implementar por
último (ordem do §11) e **re-medir na hora**. Um geocoding barato do `endereco`
do Ticket and Go era a alavanca óbvia, mas a fonte parou de expor endereço
(§0.1b), então essa porta fechou — o que sobra é o NI-16 (coordenada canônica
da casa em `curado.locais`), a mesma alavanca do §5.2.

Se mantido o gate:

- `buscar_eventos(..., perto_lat=, perto_lon=)`: ordena por distância
  haversine em SQL (expressão direta; PostGIS é overkill para o recorte DF)
  — eventos sem `lat` vão para o fim, nunca somem. Raio máximo NÃO entra no
  v1 (ordenar já responde "perto de mim"; raio esconderia evento).
- `lat`/`lon` precisam entrar em `consulta.CAMPOS` (mesmo pré-requisito do §4.2).
- API: `/api/dados/eventos?perto=<lat>,<lon>` (um parâmetro só, validado).
- Front: botão "perto de mim" que pede `navigator.geolocation` e recarrega a
  URL com `?perto=` — degradação explícita: sem JS/permissão negada, o botão
  não faz nada além de sugerir o filtro de bairro.
- **Postura:** a coordenada do visitante desce como parâmetro, é usada na
  query e NÃO é gravada nem logada; nota na página "sobre". A precisão que o
  navegador der basta (bairro-level serve). **Consequência que o PostHog
  introduziu:** a URL com `?perto=` é capturada no pageview automático, o que
  mandaria a coordenada para um terceiro — exatamente o que a postura proíbe. O
  evento de geolocalização é emitido **sem a coordenada**, e o `?perto=` entra
  na lista de parâmetros mascarados na captura de URL. Verificar na
  implementação, não presumir.

## 7. NI-52 — canal de feedback (bug, sugestão, "quero minha casa")

O item de maior valor estratégico da spec e o único sem alicerce pronto: é o que
transforma o beta em fluxo contínuo, e a categoria "quero minha casa no site"
alimenta diretamente a watchlist do Instagram (NI-24) e o estoque de fontes
(NI-27/NI-48).

### 7.1 Por que uma tabela, e não um Google Forms

O v1 barato do backlog era "mailto ou Google Forms". Descartado por decisão do
autor: o dado nasceria fora da base, sem chegar ao pipeline que já sabe relatar
(`atualizar.py`) nem perto da camada `curado`, que existe justamente para
receber decisão humana. Uma tabela é comparável em esforço — o custo real não é
o INSERT, é a rota POST (§0.2g) — e mantém o projeto com uma fonte de verdade
só.

### 7.2 Schema — `uso.feedback`

Mora em **`uso`** e não em `operacao` por causa do campo de contato: com ele a
tabela passa a conter dado pessoal, e `uso` é o schema que já carrega essa
política ("**NUNCA SE DROPA**; LGPD", como `uso.usuarios`/`uso.acessos`).
Arquivo novo `sql/uso/feedback.sql`, aplicado pelo
`conectar(aplicar_schema=True)` na ordem de `_ORDEM_DDL` — aditivo e
idempotente, sem drop de nada.

```sql
CREATE TABLE IF NOT EXISTS uso.feedback (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    em        TEXT NOT NULL,               -- ISO UTC "+00:00"
    tipo      TEXT NOT NULL,               -- bug | sugestao | casa | outro
    mensagem  TEXT NOT NULL,
    contato   TEXT,                        -- OPCIONAL: e-mail ou @ (dado pessoal)
    pagina    TEXT,                        -- de onde a pessoa clicou
    lido      INTEGER NOT NULL DEFAULT 0   -- a CLI do §7.5 marca
);
```

O que **não** entra, e por quê: **IP e user-agent ficam de fora**. Seriam úteis
para reproduzir bug e para limitar abuso por origem, mas são dado pessoal a mais
numa tabela que já vai ter contato, e o §7.4 resolve o abuso sem eles. Guardar
IP "só para rate limit" é o tipo de decisão que se justifica sozinha e nunca
mais se revê.

### 7.3 A rota — e o formulário que funciona sem JS

`POST /api/dados/feedback`, servido pelo `do_POST` novo em `api/dados.py`. A
rewrite existente (`/api/dados/:rota` → `/api/dados`) **já roteia POST**; nada
muda no `vercel.json` — o que é uma boa notícia, porque mexer nele é "o jeito
mais fácil de derrubar o MCP sem perceber" (CLAUDE.md).

O formulário é `<form method="post" action="/api/dados/feedback">` **nativo**,
sem `fetch`: é o único jeito de manter a promessa do site inteiro (funciona sem
JS). Consequências que isso impõe:

- corpo em `application/x-www-form-urlencoded`, não JSON;
- resposta **303 See Other** para `/feedback?ok=1` (e `?erro=<motivo>` no
  caminho triste) — sem redirect, quem não tem JS vê um JSON cru na tela;
- a rota `/feedback` (App Router) renderiza o form e, com `?ok=1`, a
  confirmação. É rota própria em vez de seção no `/sobre` porque precisa de
  endereço para o redirect e para o link do rodapé;
- a lógica de escrita **não mora na API**: `api/dados.py` traduz o form e chama
  uma função da camada de serviço (`servico/consulta.registrar_feedback(...)`
  ou módulo próprio, se a `consulta` se provar o lugar errado para uma escrita
  — decidir na implementação; o critério é `api/` continuar sem regra).

O `/sobre` ganha link para `/feedback` ao lado do "pedir remoção" que já existe
— mesmo lugar, papel inverso —, e o rodapé (`app/layout.jsx`) ganha o link, que
é o que o pedido original queria.

### 7.4 Abuso, sem dado pessoal e sem dependência nova

É uma escrita pública numa base Postgres do free tier do Neon (512 MiB por
branch, divididos entre os bancos). Três guardas, nesta ordem:

1. **Honeypot**: campo de texto escondido por CSS; preenchido = descarta e
   responde 303 de sucesso (bot não aprende).
2. **Tetos de tamanho**: mensagem ≤ 2000 chars, contato ≤ 200, `tipo` numa
   lista fechada. Corpo de POST é entrada de estranho — mesma postura do
   `_int`/`_str` que a API já aplica à querystring.
3. **Teto por janela, GLOBAL**: `SELECT count(*) FROM uso.feedback WHERE em >
   agora-60s`; acima de N (começar em 10), responde 429. Global e não por IP
   porque não guardamos IP (§7.2) — o custo aceito é que uma enxurrada bloqueia
   envios legítimos por um minuto, e o ganho é não ter dado pessoal extra nem
   estado de rate limit para manter. Se o abuso se provar real, a resposta certa
   é BotID/WAF da Vercel na borda, não uma tabela de IPs aqui.

Vercel BotID **não** entra no v1: é dependência nova para um problema que ainda
não existe.

### 7.5 Como o feedback chega até o autor

Sem isto, o botão é decorativo — a tabela enche e ninguém lê. Duas peças, ambas
no padrão que o projeto já usa:

- **Relatório da rodada:** o `_relatorio` do `atualizar.py` ganha uma linha
  `*** N feedbacks novos — rode python src/ferramentas/feedback.py`, no mesmo
  formato dos alertas existentes (`pendentes_extracao`, payloads reprovados).
  É o lugar certo porque é o relatório que o autor já lê todo dia.
- **`src/ferramentas/feedback.py`**, no molde do `curar.py` (fora do pipeline,
  argparse, roda da raiz):

      python src/ferramentas/feedback.py listar [--todos]
      python src/ferramentas/feedback.py lido <id>

  Sem `deletar`: o dado é curto, e apagar linha de dado de pessoa por CLI é
  exatamente o tipo de comando destrutivo que não precisa existir.

### 7.6 Postura e LGPD

A página `/sobre` ganha um parágrafo declarando o que acontece com o que a
pessoa escreve: fica numa base privada, o contato é usado só para responder
sobre aquilo, e some se ela pedir (o canal de remoção já existe ali ao lado). O
campo de contato é **rotulado como opcional na tela**, não só no schema.

## 8. NI-50 — velocidade ao trocar filtro

A queixa do beta ("parece que tá re-puxando da base toda vez que clica um
filtro") está tecnicamente certa: filtro = navegação = render novo no servidor.
**O design não sai** (filtros na URL, SSR sem JS — a Fase 2 depende dele), então
o item é sobre as alavancas que o preservam. E ele ganhou urgência nesta spec:
cada filtro novo (dia, bairro, tipo) **multiplica a matriz de combinações** e
joga mais navegação para o lado frio do cache.

Ordem — medir, depois mexer:

1. **Medir.** O PostHog já está em produção com pageview/pageleave (§0.2f);
   `$web_vitals` e a duração entre pageviews dão o número real de TTFB e de
   navegação por rota. Sem esse número, "otimizar" é achismo — e o achismo mais
   provável (o Neon frio) tem cara diferente do mais fácil (falta de feedback
   visual).
2. **`loading.jsx` — a alavanca mais barata, e hoje inexistente (§0.2j).** Um
   por rota (`/festas`, `/filmes`) faz o Next mostrar o esqueleto no clique.
   Não deixa nada mais rápido; muda o que é *percebido* como travado, que é
   literalmente a queixa.
3. **Conferir o HIT da CDN** nas combinações comuns. A API já manda
   `s-maxage=300, stale-while-revalidate=3600` e as páginas têm
   `revalidate = 300` — falta confirmar que a Vercel serve HIT de fato (header
   `x-vercel-cache`) e não revalida a cada request por algum detalhe de rota.
4. **Prefetch dos chips.** Os chips já são `<Link>`, que prefetcha no viewport
   em produção; se não estiver colando, descobrir por quê antes de inventar
   solução.
5. **Aceitar MISS na cauda longa** (texto livre, dia específico do calendário).
   Não há cache que salve combinação única — o que salva é o passo 2.

Medir de novo depois, com o mesmo instrumento. Nenhuma dessas alavancas exige
mudar a arquitetura de filtros.

## 9. Instrumentação dos elementos novos

Regra desta spec, herdada do NI-54 já implementado: **elemento novo nasce
instrumentado**, no padrão dos quatro eventos que já existem
(`ticket_link_clicked`, `other_platform_link_clicked`, `film_session_clicked`,
`event_search_performed`).

| Elemento | Evento | Propriedades |
|---|---|---|
| link "ver no mapa" (§4.2) | `map_link_clicked` | `has_coords` (coordenada ou fallback textual) |
| Google Agenda (§4.3) | `calendar_add_clicked` | — |
| compartilhar (§4.4) | `share_clicked` | `method`: `native` \| `clipboard` |
| chip de tipo (§5.3) | `filter_used` | `filter`: `tipo`, `value` |
| dropdown de bairro (§5.2) | `filter_used` | `filter`: `bairro`, `value` |
| calendário (§5.1) | `filter_used` | `filter`: `data` |
| chip sazonal (§5.4) | `filter_used` | `filter`: `colecao`, `value` |
| "perto de mim" (§6) | `nearby_used` | `granted` (sim/não) — **nunca a coordenada** (§6) |
| envio de feedback (§7) | `feedback_submitted` | `tipo` — **nunca a mensagem nem o contato** |

Um `filter_used` genérico em vez de um evento por filtro: é o que permite
responder "qual filtro as pessoas realmente usam?" numa consulta só — que é a
pergunta que decide o que fica na página depois.

## 10. Mudanças por camada (resumo)

| Camada | Mudança |
|---|---|
| `sql/tratado/eventos.sql` | `+= tipo` via `ADD COLUMN IF NOT EXISTS` **ao lado** da definição (aditivo e idempotente — sem drop, sem re-raspar) |
| `sql/uso/feedback.sql` | **novo** — tabela do §7.2 (schema `uso`: nunca se dropa, LGPD) |
| `src/coleta/` | **intocado** — nada aqui re-raspa |
| `src/tratamento/shotgun.py` | `normalizar` passa a mapear o `addressLocality` também para `bairro` (§5.2.1) |
| `src/tratamento/bairros.py` | **novo** — dicionário de RAs + `extrair(endereco)` |
| `src/tratamento/comum.py` | chama `bairros.extrair` como último passo da composição, só quando `bairro` saiu nulo (mantém UM escritor da coluna) |
| `src/tratamento/enriquecer.py` | classificação `tipo` (festa/show/NULL), idempotente; **`tipo` fora de `COLS_EVENTO`** |
| `src/servico/consulta.py` | `CAMPOS += lat, lon`; `buscar_eventos` += `bairro` (multi), `tipo`, `gratis` (§5.5), `perto_lat/lon` (§6); `facetas_eventos()` nova; escrita do feedback (§7.3) |
| `api/dados.py` | traduz params novos; `facetas` na resposta de `/eventos`; `?perto=`; **`do_POST` p/ `/feedback`** (§7.3) — primeiro método de escrita da API |
| `src/pipeline/atualizar.py` | `_relatorio` avisa feedback não lido (§7.5) |
| `src/ferramentas/feedback.py` | **novo** — CLI `listar` / `lido` (§7.5) |
| `app/festas/` | resumo no card, chip "próximos", calendário, dropdown bairro, chips tipo, chip sazonal, `loading.jsx` |
| `app/evento/[id]/` | link "ver no mapa", Google Agenda, compartilhar |
| `app/feedback/` | **nova rota** — formulário + confirmação (§7.3) |
| `app/sobre/page.jsx` | link para `/feedback` + parágrafo de postura (§7.6) + nota do `?perto=` (§6) |
| `app/layout.jsx` | link de feedback no rodapé |
| `app/Calendario.jsx`, `app/Drop.jsx`, `app/DropFiltro.jsx` | **movidos** de `app/filmes/` (§5.1) — toca a página de cinema, conferir depois |
| `lib/` | `config.js` += período "próximos"; `colecoes.js` novo; `formato.js` += data UTC compacta do Google Agenda |
| `vercel.json` | **intocado** — a rewrite existente já roteia POST (§7.3) |
| MCP (`src/servico/mcp_server.py`) | **sem tool nova**; `buscar_eventos` anuncia os parâmetros novos na descrição da tool |

## 11. Ordem de implementação (cada etapa entrega valor sozinha)

1. **NI-41 — busca por casa** (§3): é bug com cara de produto quebrado;
   front + teste, zero schema. *Quick win, primeiro.*
2. **NI-38 + NI-39 + NI-51 + NI-53 — card e detalhe** (§4): resumo, mapa,
   agenda e compartilhar. Só front (+ `lat`/`lon` em `CAMPOS`), e é a leva que
   o beta mais pediu.
3. **NI-45a — bairro do Shotgun** (§5.2.1): uma linha em
   `tratamento/shotgun.py` + `--so-derivar`. Leva a cobertura de 23% para ~41%
   e não depende de mais nada.
4. **NI-52 — feedback** (§7): schema + rota POST + página + CLI + relatório.
   Sobe **cedo** de propósito: é o item que passa a colher reação às etapas
   seguintes enquanto elas ainda estão sendo feitas.
5. **NI-50 — velocidade** (§8): `loading.jsx` e a conferência de cache ANTES
   de a página ganhar mais três filtros — assim a diferença fica medível.
6. **NI-43 — calendário** (§5.1): `facetas_eventos()` (só `dias`) + API +
   front + o move dos componentes compartilhados. Zero schema.
7. **NI-45b + NI-44 + §5.5 — dicionário de bairro, tipo e o `gratis`**
   (§5.2.2, §5.3): coluna aditiva + derivação/enriquecimento a seco
   (`--so-derivar` / `--so-enriquecer`), depois faceta/filtros/chips. Sem drop,
   sem re-raspar.
8. **NI-47 — sazonais** (§5.4): a qualquer momento, é `lib/` puro.
9. **NI-46 — perto de mim** (§6): por último, atrás do gate de cobertura.

## 12. Plano de teste e validação

### 12.1 Testes automatizados

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
  `tipo`/`gratis`/`perto` traduzidos; **`gratis` filtra na consulta e não na
  fatia** (§5.5 — pedir grátis com limite baixo devolve grátis, não sobras);
  **POST de feedback**: grava, rejeita tipo inválido, corta tamanho, honeypot
  descarta, teto por janela devolve 429; postura preservada (organizador
  oculto, trecho).
- `tests/test_mcp_server.py`: parâmetros novos aceitos pela tool.

### 12.2 Validação no navegador (autonomia acordada)

O projeto não tem teste de front, e três itens desta spec (compartilhar,
geolocalização, envio de formulário) só existem no navegador. A validação usa a
skill `webapp-testing` (Playwright) contra `npm run dev` na 1007, com a API de
leitura local (`python api/dados.py 8000`) apontando para a base **real** —
leitura, e a única escrita nova é o feedback, que é aditivo por natureza.

Fluxo de ponta a ponta a exercitar antes de dar cada etapa por pronta: buscar
"Ordinário" → chegar a um evento → mapa/agenda/compartilhar → enviar um
feedback de teste → ver a linha pelo `ferramentas/feedback.py`. Os dois temas e
o mobile seguem o padrão do projeto.

### 12.3 Regime de execução (decidido em 2026-07-28, antes de começar)

**Validação só local — nenhum deploy, nem preview.** O rascunho previa subir um
preview (`vercel`, sem `--prod`) para provar o que só existe em ambiente real. Foi
descartado por duas razões, uma de fato e uma de escopo: `vercel env ls` mostra
`EVENTOS_DB_URL` **só em Production**, então um preview subiria sem banco e
provaria menos que o local; e o deploy é do autor, por decisão registrada. Tudo se
valida com `npm run dev` (:1007) + `python api/dados.py 8000` contra a base real.

**O que fica sem prova, declarado e não omitido:**

- **A rota POST rodando como função serverless.** O `handler` é a mesma classe,
  mas não o mesmo empacotamento — e é exatamente o cenário do **NI-61** (o MCP em
  500 em produção, com suspeita de bundle Python). Teste de um minuto para o autor
  fazer depois do `--prod`: enviar um feedback pelo site e conferir a linha com
  `python src/ferramentas/feedback.py listar`. Se o bundle não levar `src/`
  inteiro, é ali que aparece.
- **Os eventos do PostHog.** As envs `NEXT_PUBLIC_POSTHOG_KEY`/`_HOST` existem só
  em Production (§0.2f), então em local a instrumentação do §9 **não emite**. O que
  se valida aqui é que o handler está ligado e não quebra a interação; que o evento
  chega, só o autor vê.

**Base de produção, com rede de segurança.** As escritas desta spec são aditivas
(`ADD COLUMN`, `CREATE TABLE`, INSERT de feedback) e as reconstruções são as de
sempre (`--so-derivar` / `--so-enriquecer`, que refazem a prata do cru). Ainda
assim: **branch no Neon antes do primeiro `--so-derivar`**, conferindo a cota antes
de criar (512 MiB **por branch**, e já há branches de 28/07 esperando o drop do
legado). Nenhum `DROP SCHEMA`, nenhum `TRUNCATE`, nenhum comando destrutivo em
`cru`/`curado`/`operacao`/`uso`.

**Commits por etapa do §11, em português, na `main`, sem push.** O autor revisa no
fim; o `git log` é o roteiro da revisão. O `vercel --prod` é do autor — e vale a
lembrança de que o deploy publica o **diretório local**, não o `main`: conferir
`git status` antes.

## 13. Riscos e decisões registradas

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
- **Mover `Calendario`/`Drop`/`DropFiltro` mexe na página de cinema**, que está
  pronta e fora de revisão (§5.1). É a única regressão possível desta spec em
  código que já funciona — conferir `/filmes` logo depois do move.
- **`facetas_eventos()` é mais uma query por render** — sai na MESMA
  resposta cacheada da CDN (`/api/dados/eventos`), então o custo real é ~0
  em HIT; conferir que não degrada o TTFB em MISS (liga com o §8).
- **Os filtros novos multiplicam a matriz de cache** — três filtros novos
  transformam a cauda longa em maioria. É o motivo de o §8 vir ANTES deles na
  ordem do §11.
- **Escrita pública na base** (§7): a primeira do projeto. Guardas no §7.4; o
  free tier do Neon (512 MiB por branch, compartilhados entre os bancos) é o
  recurso a proteger, e o teto por janela é o que o protege.
- **Contato no feedback é dado pessoal** — por isso a tabela mora em `uso`
  (nunca se dropa, LGPD), o campo é opcional e declarado na tela, e nem IP nem
  user-agent são guardados (§7.2).
- **Privacidade do `?perto=`** — coordenada não é persistida em lugar nenhum,
  **inclusive no PostHog**: o parâmetro entra na lista de mascarados da captura
  de URL e o evento `nearby_used` não carrega coordenada (§6, §9).
- **Schema aditivo, sem drop**: `tipo` entra por `ADD COLUMN IF NOT EXISTS` em
  `sql/tratado/eventos.sql`, `uso.feedback` por `CREATE TABLE IF NOT EXISTS`;
  mudança não-aditiva segue a regra (b) da convenção (dropar só derivadas), e
  desde a fatia 7 do medalhão `tratado` inteira é reconstruível.
- **Um escritor por coluna** (§0.1a) — é a decisão de desenho que a revisão de
  28/07 acrescentou, e a que mais muda código em relação ao rascunho. Vale
  para tudo que esta spec escrever em `tratado.eventos` daqui para frente.
- **O backlog mentiu uma vez** (NI-54 dado como não-iniciado quando já estava
  em produção havia dois dias — §0.2f). O custo teria sido instalar um segundo
  analytics em cima do primeiro. Antes de implementar item de backlog datado de
  antes da última entrega, conferir no código — foi o que esta revisão fez, e é
  o que ela recomenda como hábito.

## 14. O que a execução mudou (2026-07-28)

As nove etapas do §11 foram executadas na ordem, cada uma com commit próprio,
validadas contra a **base de produção** e no navegador (Playwright). O que
segue é o registro do que a spec previu errado, do que apareceu no caminho e
do que ficou de fora — não um relatório de progresso.

### 14.1 O placar

| Item | Entregue |
|---|---|
| NI-41 busca por casa | sim — chip "próximos" + default que depende da busca |
| NI-38 resumo no card | sim |
| NI-39 ver no mapa | sim — coordenada vence, fallback textual |
| NI-51 Google Agenda | sim |
| NI-53 compartilhar | sim — share nativo → clipboard, com UTM |
| NI-45 bairro | **parcial** — 23% → 56%; o teto restante é NI-16 |
| NI-52 feedback | sim — tabela, rota POST, página, CLI, alerta na rodada |
| NI-50 velocidade | sim — e o achado mudou o plano (§14.3) |
| NI-43 calendário | sim — 3 meses + "+N dias depois de \<mês\>" |
| NI-44 festa × show | **parcial** — tudo pronto, chips escondidos (§14.4) |
| NI-47 sazonais | sim — só "festa junina" renderiza em julho |
| NI-46 perto de mim | sim — gate re-medido em 69%, passou |

### 14.2 Três previsões que a base real desmentiu

**(a) O bairro do Shotgun não eram 68 eventos, eram 32.** A spec dizia que o
`addressLocality` "É o bairro" e que copiá-lo levaria a cobertura a ~41%. Na
base: **38 dos 70 payloads dizem "Brasília"** — a cidade. Cidade não é bairro,
e deixá-la passar encheria a faceta com uma opção que casa tudo. Em
compensação, o mesmo mergulho achou algo que a spec não previu: o
`streetAddress` (endereço COMPLETO, presente em 68 dos 70) **estava sendo
descartado** porque a localidade tinha precedência no `or`. Corrigido, ele
virou a matéria-prima do dicionário do §5.2.2 — que era exatamente o que a
spec dava por perdido quando o Ticket and Go parou de expor endereço.

**(b) A canonização de grafia não era um detalhe.** A spec a mencionou de
passagem ("unaccent + caixa para a faceta não listar duas vezes"). A base
tinha **44 grafias para 32 regiões**: "Asa Norte"/"ASA NORTE"/"asa norte",
"Saan"/"SAAN", "Samambaia sul"/"Samambaia Norte", "São Sebastião/DF". Sem o
`canonizar()`, o dropdown do §5.2.3 nasceria com um terço das opções
duplicadas — e cada duplicata devolvendo uma fatia dos eventos.

**(c) `categoria` não ajuda em nada no tipo.** A spec contava com ela para
~187 dos 379 eventos ("só o Sympla preenche desde 28/07"). Preenche, mas com
`"musica"` em 155 dos 187 — que não distingue festa de show. Na prática o
passo 1 da heurística **nunca dispara**, e a palavra no nome carrega o item
sozinha. É a raiz do §14.4.

### 14.3 O que a medição do NI-50 achou

A ordem "medir, depois mexer" do §8 se pagou duas vezes:

- **`loading.jsx` não cobre troca de filtro.** Ele só entra quando o SEGMENTO
  de rota muda, e `/festas?periodo=hoje` → `?periodo=7d` é a mesma rota. Ou
  seja: a alavanca que a spec chamou de "a mais barata, e hoje inexistente"
  não tocava no gesto de que o beta reclamou. O que resolve é
  `<Suspense key={filtros}>` em volta da parte que depende da base.
- **O handshake com o Neon custa mais que a query** (147 ms contra ~80 ms
  deste lado da rede). A rota de cinema fazia duas consultas e pagava dois
  handshakes por render: 423 ms → 269 ms passando UMA conexão por requisição.
  Isso responde, por antecipação, o risco que o §13 levantava sobre a
  `facetas_eventos()` ser "mais uma query por render" — ela não abre conexão
  nova.
- O **prefetch dos `<Link>` já funcionava** (item 4 do §8): com ele quente a
  navegação é instantânea e o esqueleto nem aparece. Ele cobre o cache frio.

### 14.4 O NI-44 está pronto e escondido, de propósito

Coluna `tipo`, enriquecimento idempotente, parâmetro na consulta/API/MCP e os
chips no front: tudo existe e tem teste. **Os chips não aparecem** porque a
heurística classifica **24% da agenda** (91 de 379), e a semântica é inclusiva
por princípio — `tipo=festa` traz também os sem rótulo, porque errar para o
lado de esconder festa real é o pior erro possível aqui. Com 3 de 4 eventos
sem rótulo, o chip devolveria a lista inteira: um filtro que promete um
recorte e entrega tudo é pior que filtro nenhum.

O gate é sobre o DADO, não sobre a UI: `facetas_eventos()` devolve as
CONTAGENS por tipo e o front acende os chips ao passar de 50%
(`COBERTURA_TIPO`). Quando o NI-05 (LLM) assumir a coluna, ninguém precisa
mexer em código. É o mesmo desenho do gate de cobertura do §6 — que, aliás,
foi re-medido na hora e **passou** (69%).

### 14.5 Dois bugs que só a execução revelaria

- **`least(1, NULL)` no Postgres devolve 1**, porque `least` ignora nulos ao
  contrário de quase todo operador. Na haversine, isso fazia todo evento sem
  coordenada — 30% da base — sair com `acos(1) = 0`, ou seja **"0,0 km"**:
  exatamente onde a pessoa está. Mentira com cara de precisão, que é o pior
  modo de falha deste recurso.
- **Função não atravessa a fronteira server → client.** Passar `href={(x) =>
  …}` para o `<PertoDeMim>` fez o React descartar o componente: a página
  renderizou sem o botão, **sem erro na tela**. O padrão do projeto (o mesmo
  do `DropFiltro`) é passar `base` + `estado` como strings.

### 14.6 O que ficou de fora, e por quê

- **Os chips de tipo** (§14.4) — esperando cobertura, não código.
- **112 eventos sem bairro** (Ticket and Go e Instagram, que não expõem
  endereço nenhum). O caminho é o NI-16, como a spec já dizia.
- **Prova em ambiente serverless.** Por decisão registrada na §12.3, a
  validação foi só local. O que isso deixa sem cobertura é a rota POST do
  feedback rodando como função na Vercel — o cenário do NI-61. Teste de um
  minuto depois do `--prod`: enviar um feedback pelo site e conferir a linha
  com `python src/ferramentas/feedback.py listar`.
- **Os eventos do PostHog.** As envs existem só em Production; em local a
  instrumentação não emite. O que se validou é que os handlers estão ligados
  e não quebram a interação.

### 14.7 Um achado que não é desta spec

O chip "festa junina" traz eventos que não são juninos — por exemplo um show
de pop rock. A causa não é o chip: **eventos derivados de carrossel-agenda do
Instagram carregam a legenda INTEIRA como descrição** (a semana toda, não só o
item), e o FTS indexa descrição. Afeta qualquer busca textual do site, não só
este chip. É matéria da derivação do Instagram.
