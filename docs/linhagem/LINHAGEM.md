# Linhagem — a trajetória do dado

> **Arquivo gerado. Não edite à mão.** Regrave com
> `python src/ferramentas/linhagem.py` — ele lê o próprio código, então
> fonte nova aparece aqui sozinha. O porquê de ser um gerador e não uma
> ferramenta de prateleira está em
> `docs/pesquisas/20260802_ferramentas-linhagem.md`.

Os diagramas são cortes do MESMO grafo, do mais geral para o mais
detalhado. A cor é a camada; o cinza-azulado à esquerda é sempre o que
está fora daqui.

> Para apresentar, tem o [`linhagem.excalidraw`](linhagem.excalidraw) aqui
> do lado ([prévia](linhagem.png)): as mesmas camadas desenhadas à mão,
> com as caixas arrastáveis. **Ele é um snapshot — não se regenera com
> este arquivo e não acompanha mudança no pipeline.** Em qualquer
> divergência, quem vale é este documento.

## 1. Panorâmica

A regra que o desenho inteiro serve: **tudo que tem rede é coleta e
escreve só em `cru`/`operacao`; tudo que é a seco é tratamento, e ele é o
único que escreve em `tratado`.**

```mermaid
flowchart LR
  f1["5 plataformas de ingresso<br/>Sympla · Ingresse · Zig · Shotgun · Ticket and Go"]
  f2["3 fontes de contrato próprio<br/>cinema · Instagram · TMDB"]
  c["coleta/<br/>tudo que tem rede"]
  b["cru — 9 tabelas<br/>o payload como a fonte mandou"]
  t["tratamento/<br/>a seco, 8 passos numa transação"]
  p["tratado — 4 tabelas<br/>o schema unificado"]
  h["curado — 3<br/>decisão humana"]
  o["operacao — 4<br/>telemetria"]
  v["public — 5 views<br/>o contrato de consumo"]
  s["2 portas<br/>site · MCP"]
  f1 --> c
  f2 --> c
  c --> b
  b --> t
  t --> p
  h --> t
  o --> t
  t --> o
  p --> v
  v --> s
  classDef fonte fill:#eceef0,stroke:#8b949e,color:#24292f
  classDef coleta fill:#dceaf7,stroke:#3f7cae,color:#12304a
  classDef cru fill:#f6e6cd,stroke:#a8722c,color:#4a3214
  classDef tratamento fill:#e7e2f3,stroke:#6b5ca5,color:#2e2650
  classDef tratado fill:#e6e9ec,stroke:#6b7280,color:#2b3138
  classDef curado fill:#dfe3f6,stroke:#4c5fa8,color:#232c5a
  classDef operacao fill:#e6ecd8,stroke:#6b7f3a,color:#2f3a19
  classDef public fill:#d7ecea,stroke:#0f6e6e,color:#0a3b3b
  classDef consumo fill:#c9e4e1,stroke:#0b5450,color:#062f2d
  class f1,f2 fonte
  class c coleta
  class b cru
  class t tratamento
  class p tratado
  class h curado
  class o operacao
  class v public
  class s consumo
```

## 2. As plataformas de ingresso

Uma trilha por fonte, e todas desembocam no mesmo motor: o
`tratamento/comum.py` faz o upsert em `tratado.eventos` e agrega os lotes.
O módulo da fonte não sabe SQL — ele só declara como ler o payload dela.

```mermaid
flowchart LR
  subgraph g_fonte["fontes externas"]
    direction TB
    ext_ingresse["ingresse<br/>api-site-events · api-site-search · api-site-tickets"]
    ext_shotgun["shotgun<br/>json-ld"]
    ext_sympla["sympla<br/>discovery-bff · event-page-bff · event-page-bff-tickets"]
    ext_ticketandgo["ticketandgo<br/>v1-evento"]
    ext_zig["zig<br/>next-data · superticket-events"]
  end
  subgraph g_coleta["coleta/ — só fala com a fonte"]
    direction TB
    col_gravar["coleta/gravar.py<br/>a única escrita em cru"]
    col_cinema["coleta/cinema.py"]
    col_ingresse["coleta/ingresse.py"]
    col_instagram["coleta/instagram.py"]
    col_shotgun["coleta/shotgun.py"]
    col_sympla["coleta/sympla.py"]
    col_ticketandgo["coleta/ticketandgo.py"]
    col_tmdb["coleta/tmdb.py"]
    col_zig["coleta/zig.py"]
  end
  subgraph g_cru["cru — bronze: o que a fonte disse. NUNCA SE DROPA"]
    direction TB
    cru_cinema["cru.cinema<br/>nao se dropa, mas e a UNICA bronze com PODA…"]
    cru_ingresse["cru.ingresse<br/>NUNCA SE DROPA e APPEND-ONLY."]
    cru_instagram["cru.instagram<br/>NUNCA SE DROPA."]
    cru_shotgun["cru.shotgun<br/>NUNCA SE DROPA e APPEND-ONLY."]
    cru_sympla["cru.sympla<br/>NUNCA SE DROPA e APPEND-ONLY."]
    cru_ticketandgo["cru.ticketandgo<br/>NUNCA SE DROPA e APPEND-ONLY."]
    cru_tmdb["cru.tmdb<br/>NUNCA SE DROPA, ACUMULATIVA e fora do snapsh…"]
    cru_zig["cru.zig<br/>NUNCA SE DROPA e APPEND-ONLY."]
  end
  subgraph g_tratamento["tratamento/ — a seco, nenhuma rede"]
    direction TB
    tratamento_comum["tratamento/comum.py"]
    tratamento_sympla["tratamento/sympla.py<br/>trilha da fonte"]
    tratamento_ingresse["tratamento/ingresse.py<br/>trilha da fonte"]
    tratamento_zig["tratamento/zig.py<br/>trilha da fonte"]
    tratamento_shotgun["tratamento/shotgun.py<br/>trilha da fonte"]
    tratamento_ticketandgo["tratamento/ticketandgo.py<br/>trilha da fonte"]
  end
  subgraph g_tratado["tratado — prata: o schema unificado. Descartável por desenho"]
    direction TB
    tratado_eventos["tratado.eventos<br/>descartavel POR DESENHO — tem que se reconst…"]
    tratado_lotes["tratado.lotes<br/>100% descartavel e ja e reconstruida do zero…"]
  end
  col_cinema --> col_gravar
  col_gravar --> cru_cinema
  col_ingresse --> col_gravar
  ext_ingresse --> col_ingresse
  col_gravar --> cru_ingresse
  col_instagram --> col_gravar
  col_gravar --> cru_instagram
  col_shotgun --> col_gravar
  ext_shotgun --> col_shotgun
  col_gravar --> cru_shotgun
  col_sympla --> col_gravar
  ext_sympla --> col_sympla
  col_gravar --> cru_sympla
  col_ticketandgo --> col_gravar
  ext_ticketandgo --> col_ticketandgo
  col_gravar --> cru_ticketandgo
  col_tmdb --> col_gravar
  col_gravar --> cru_tmdb
  col_zig --> col_gravar
  ext_zig --> col_zig
  col_gravar --> cru_zig
  cru_sympla --> tratamento_comum
  cru_ingresse --> tratamento_comum
  cru_zig --> tratamento_comum
  cru_shotgun --> tratamento_comum
  cru_ticketandgo --> tratamento_comum
  tratamento_comum --> tratado_eventos
  tratamento_comum --> tratado_lotes
  cru_sympla --> tratamento_sympla
  tratamento_sympla --> tratamento_comum
  cru_ingresse --> tratamento_ingresse
  tratamento_ingresse --> tratamento_comum
  cru_zig --> tratamento_zig
  tratamento_zig --> tratamento_comum
  cru_shotgun --> tratamento_shotgun
  tratamento_shotgun --> tratamento_comum
  cru_ticketandgo --> tratamento_ticketandgo
  tratamento_ticketandgo --> tratamento_comum
  classDef fonte fill:#eceef0,stroke:#8b949e,color:#24292f
  class ext_ingresse,ext_shotgun,ext_sympla,ext_ticketandgo,ext_zig fonte
  classDef coleta fill:#dceaf7,stroke:#3f7cae,color:#12304a
  class col_gravar,col_cinema,col_ingresse,col_instagram,col_shotgun,col_sympla,col_ticketandgo,col_tmdb,col_zig coleta
  classDef cru fill:#f6e6cd,stroke:#a8722c,color:#4a3214
  class cru_cinema,cru_ingresse,cru_instagram,cru_shotgun,cru_sympla,cru_ticketandgo,cru_tmdb,cru_zig cru
  classDef tratamento fill:#e7e2f3,stroke:#6b5ca5,color:#2e2650
  class tratamento_comum,tratamento_sympla,tratamento_ingresse,tratamento_zig,tratamento_shotgun,tratamento_ticketandgo tratamento
  classDef tratado fill:#e6e9ec,stroke:#6b7280,color:#2b3138
  class tratado_eventos,tratado_lotes tratado
```

## 3. Cinema

Tratamento do CINEMA: `cru.cinema` (+ `cru.tmdb`, `operacao.midias`) → `tratado.filmes` e `tratado.sessoes`.

```mermaid
flowchart LR
  subgraph g_fonte["fontes externas"]
    direction TB
    ext_cinema["cinema"]
    ext_tmdb["tmdb"]
  end
  subgraph g_coleta["coleta/ — só fala com a fonte"]
    direction TB
    col_gravar["coleta/gravar.py<br/>a única escrita em cru"]
    col_cinema["coleta/cinema.py"]
    col_tmdb["coleta/tmdb.py"]
  end
  subgraph g_cru["cru — bronze: o que a fonte disse. NUNCA SE DROPA"]
    direction TB
    cru_cinema["cru.cinema<br/>nao se dropa, mas e a UNICA bronze com PODA…"]
    cru_tmdb["cru.tmdb<br/>NUNCA SE DROPA, ACUMULATIVA e fora do snapsh…"]
  end
  subgraph g_tratamento["tratamento/ — a seco, nenhuma rede"]
    direction TB
    tratamento_cinema["tratamento/cinema.py"]
  end
  subgraph g_tratado["tratado — prata: o schema unificado. Descartável por desenho"]
    direction TB
    tratado_filmes["tratado.filmes<br/>100% descartavel — derivar.aplicar_cinema re…"]
    tratado_sessoes["tratado.sessoes<br/>100% descartavel."]
  end
  subgraph g_operacao["operacao — telemetria e artefatos nossos. NUNCA SE DROPA"]
    direction TB
    operacao_midias["operacao.midias<br/>NUNCA SE DROPA."]
  end
  col_cinema --> col_gravar
  ext_cinema --> col_cinema
  col_gravar --> cru_cinema
  col_tmdb --> col_gravar
  ext_tmdb --> col_tmdb
  col_gravar --> cru_tmdb
  cru_cinema --> tratamento_cinema
  cru_tmdb --> tratamento_cinema
  operacao_midias --> tratamento_cinema
  tratamento_cinema --> tratado_filmes
  tratamento_cinema --> tratado_sessoes
  classDef fonte fill:#eceef0,stroke:#8b949e,color:#24292f
  class ext_cinema,ext_tmdb fonte
  classDef coleta fill:#dceaf7,stroke:#3f7cae,color:#12304a
  class col_gravar,col_cinema,col_tmdb coleta
  classDef cru fill:#f6e6cd,stroke:#a8722c,color:#4a3214
  class cru_cinema,cru_tmdb cru
  classDef tratamento fill:#e7e2f3,stroke:#6b5ca5,color:#2e2650
  class tratamento_cinema tratamento
  classDef tratado fill:#e6e9ec,stroke:#6b7280,color:#2b3138
  class tratado_filmes,tratado_sessoes tratado
  classDef operacao fill:#e6ecd8,stroke:#6b7f3a,color:#2f3a19
  class operacao_midias operacao
```

## 4. Instagram

Tratamento do INSTAGRAM: `cru.instagram` (post + extração do flyer) → eventos `fonte='instagram'` em `tratado.eventos`.

```mermaid
flowchart LR
  subgraph g_fonte["fontes externas"]
    direction TB
    ext_instagram["instagram"]
  end
  subgraph g_coleta["coleta/ — só fala com a fonte"]
    direction TB
    col_gravar["coleta/gravar.py<br/>a única escrita em cru"]
    col_instagram["coleta/instagram.py"]
  end
  subgraph g_cru["cru — bronze: o que a fonte disse. NUNCA SE DROPA"]
    direction TB
    cru_instagram["cru.instagram<br/>NUNCA SE DROPA."]
  end
  subgraph g_tratamento["tratamento/ — a seco, nenhuma rede"]
    direction TB
    tratamento_instagram["tratamento/instagram.py"]
  end
  subgraph g_tratado["tratado — prata: o schema unificado. Descartável por desenho"]
    direction TB
    tratado_eventos["tratado.eventos<br/>descartavel POR DESENHO — tem que se reconst…"]
    tratado_lotes["tratado.lotes<br/>100% descartavel e ja e reconstruida do zero…"]
  end
  subgraph g_operacao["operacao — telemetria e artefatos nossos. NUNCA SE DROPA"]
    direction TB
    operacao_midias["operacao.midias<br/>NUNCA SE DROPA."]
  end
  col_instagram --> col_gravar
  ext_instagram --> col_instagram
  col_gravar --> cru_instagram
  cru_instagram --> tratamento_instagram
  operacao_midias --> tratamento_instagram
  tratamento_instagram --> tratado_eventos
  tratamento_instagram --> tratado_lotes
  classDef fonte fill:#eceef0,stroke:#8b949e,color:#24292f
  class ext_instagram fonte
  classDef coleta fill:#dceaf7,stroke:#3f7cae,color:#12304a
  class col_gravar,col_instagram coleta
  classDef cru fill:#f6e6cd,stroke:#a8722c,color:#4a3214
  class cru_instagram cru
  classDef tratamento fill:#e7e2f3,stroke:#6b5ca5,color:#2e2650
  class tratamento_instagram tratamento
  classDef tratado fill:#e6e9ec,stroke:#6b7280,color:#2b3138
  class tratado_eventos,tratado_lotes tratado
  classDef operacao fill:#e6ecd8,stroke:#6b7f3a,color:#2f3a19
  class operacao_midias operacao
```

## 5. Curadoria, telemetria e endereços

O que não vem de fonte nenhuma: a decisão humana (`curado`), o que a
própria rodada registrou sobre si (`operacao`) e o endereço público de
cada registro. É daqui que sai o `sumido` — evento que não reapareceu no
catálogo —, e é por isso que ele depende de `operacao.coletas` ter
registrado uma coleta boa.

```mermaid
flowchart LR
  subgraph g_cru["cru — bronze: o que a fonte disse. NUNCA SE DROPA"]
    direction TB
    cru_instagram["cru.instagram<br/>NUNCA SE DROPA."]
    cru_tmdb["cru.tmdb<br/>NUNCA SE DROPA, ACUMULATIVA e fora do snapsh…"]
    cru_inventario["cru.inventario<br/>view"]
  end
  subgraph g_tratamento["tratamento/ — a seco, nenhuma rede"]
    direction TB
    tratamento_busca["tratamento/busca.py"]
    tratamento_curadoria["tratamento/curadoria.py"]
    tratamento_enriquecer["tratamento/enriquecer.py"]
    tratamento_slug["tratamento/slug.py"]
    tratamento_sumido["tratamento/sumido.py"]
  end
  subgraph g_tratado["tratado — prata: o schema unificado. Descartável por desenho"]
    direction TB
    tratado_eventos["tratado.eventos<br/>descartavel POR DESENHO — tem que se reconst…"]
    tratado_filmes["tratado.filmes<br/>100% descartavel — derivar.aplicar_cinema re…"]
  end
  subgraph g_curado["curado — o que uma PESSOA decidiu. NUNCA SE DROPA"]
    direction TB
    curado_correcoes["curado.correcoes<br/>NUNCA SE DROPA e APPEND-ONLY."]
    curado_locais["curado.locais<br/>NUNCA SE DROPA."]
    curado_pendencias["curado.pendencias<br/>view"]
  end
  subgraph g_operacao["operacao — telemetria e artefatos nossos. NUNCA SE DROPA"]
    direction TB
    operacao_coletas["operacao.coletas<br/>NUNCA SE DROPA."]
    operacao_execucoes["operacao.execucoes<br/>NUNCA SE DROPA."]
    operacao_midias["operacao.midias<br/>NUNCA SE DROPA."]
    operacao_slugs["operacao.slugs<br/>append-only por `slug` — o slug e a chave, e…"]
  end
  subgraph g_pipeline["pipeline/ — orquestração da rodada"]
    direction TB
    pipeline_atualizar["pipeline/atualizar.py"]
    pipeline_execucoes["pipeline/execucoes.py"]
  end
  subgraph g_ferramentas["ferramentas/ — fora do pipeline"]
    direction TB
    ferramentas_curar["ferramentas/curar.py"]
    ferramentas_linhagem["ferramentas/linhagem.py"]
  end
  tratamento_busca --> tratado_eventos
  tratamento_busca --> tratado_filmes
  curado_correcoes --> tratamento_curadoria
  curado_locais --> tratamento_curadoria
  curado_pendencias --> tratamento_curadoria
  tratamento_curadoria --> tratado_eventos
  tratamento_enriquecer --> tratado_eventos
  tratado_eventos --> tratamento_slug
  tratado_filmes --> tratamento_slug
  tratamento_slug --> operacao_slugs
  operacao_coletas --> tratamento_sumido
  tratamento_sumido --> tratado_eventos
  cru_instagram --> pipeline_atualizar
  cru_inventario --> pipeline_atualizar
  cru_tmdb --> pipeline_atualizar
  operacao_execucoes --> pipeline_atualizar
  operacao_midias --> pipeline_atualizar
  tratado_eventos --> pipeline_atualizar
  tratado_filmes --> pipeline_atualizar
  pipeline_execucoes --> operacao_coletas
  pipeline_execucoes --> operacao_execucoes
  tratado_eventos --> ferramentas_curar
  ferramentas_curar --> curado_correcoes
  ferramentas_curar --> curado_locais
  ferramentas_linhagem --> tratado_eventos
  classDef cru fill:#f6e6cd,stroke:#a8722c,color:#4a3214
  class cru_instagram,cru_tmdb,cru_inventario cru
  classDef tratamento fill:#e7e2f3,stroke:#6b5ca5,color:#2e2650
  class tratamento_busca,tratamento_curadoria,tratamento_enriquecer,tratamento_slug,tratamento_sumido tratamento
  classDef tratado fill:#e6e9ec,stroke:#6b7280,color:#2b3138
  class tratado_eventos,tratado_filmes tratado
  classDef curado fill:#dfe3f6,stroke:#4c5fa8,color:#232c5a
  class curado_correcoes,curado_locais,curado_pendencias curado
  classDef operacao fill:#e6ecd8,stroke:#6b7f3a,color:#2f3a19
  class operacao_coletas,operacao_execucoes,operacao_midias,operacao_slugs operacao
  classDef pipeline fill:#e3e6e9,stroke:#5b6b7a,color:#232c33
  class pipeline_atualizar,pipeline_execucoes pipeline
  classDef ferramentas fill:#f0e8dd,stroke:#8a7154,color:#3d3125
  class ferramentas_curar,ferramentas_linhagem ferramentas
```

## 6. O ciclo do tratamento

O segundo tempo de toda rodada (`tratamento/ciclo.py`), na ordem lida do
código. Roda numa transação só: enquanto reconstrói `tratado`, o site e o
MCP seguem lendo a versão anterior por `public`.

```mermaid
flowchart TD
  p0["1. comum.aplicar()<br/>escreve: eventos, lotes"]
  p1["2. instagram.aplicar()<br/>escreve: eventos, lotes"]
  p0 --> p1
  p2["3. cinema.aplicar()<br/>escreve: filmes, sessoes"]
  p1 --> p2
  p3["4. sumido.aplicar()<br/>escreve: eventos"]
  p2 --> p3
  p4["5. enriquecer.aplicar()<br/>escreve: eventos"]
  p3 --> p4
  p5["6. curadoria.aplicar()<br/>escreve: eventos"]
  p4 --> p5
  p6["7. slug.aplicar()<br/>escreve: slugs"]
  p5 --> p6
  p7["8. busca.reconstruir_fts()<br/>escreve: eventos, filmes"]
  p6 --> p7
  commit["um commit — o site e o MCP só veem o depois"]
  p7 --> commit
  classDef passo fill:#e7e2f3,stroke:#6b5ca5,color:#2e2650
  class p0,p1,p2,p3,p4,p5,p6,p7 passo
  classDef fim fill:#d7ecea,stroke:#0f6e6e,color:#0a3b3b
  class commit fim
```

## 7. Trilha por fonte

As colunas de origem dizem qual endpoint produziu cada payload
(`gravar.ERAS`) e o que cada um alimenta.

| fonte | endpoints por origem | bronze | trilha | derivações | lotes |
|---|---|---|---|---|---|
| **sympla** | `catalogo`: discovery-bff, `detalhe`: event-page-bff, `tickets`: event-page-bff-tickets | `cru.sympla` | `tratamento/sympla.py` | catalogo, detalhe | tickets |
| **ingresse** | `catalogo`: api-site-search, `detalhe`: api-site-events, `tickets`: api-site-tickets | `cru.ingresse` | `tratamento/ingresse.py` | detalhe | tickets |
| **zig** | `catalogo`: superticket-events, `detalhe`: superticket-events, `tickets`: next-data | `cru.zig` | `tratamento/zig.py` | catalogo, detalhe | tickets |
| **shotgun** | `catalogo`: json-ld | `cru.shotgun` | `tratamento/shotgun.py` | catalogo | catalogo |
| **ticketandgo** | `catalogo`: v1-evento, `tickets`: v1-evento | `cru.ticketandgo` | `tratamento/ticketandgo.py` | — | tickets |

## 8. Inventário por camada

Cada objeto do DDL, a política declarada no cabeçalho do `.sql` dele e
quem o toca no código. É esta tabela que responde "posso dropar isto?".

Duas leituras do quadro: um módulo que **escreve** numa tabela quase
sempre também a lê, e a coluna "lido por" só lista quem lê SEM escrever;
e as views `cru.<fonte>_atual` — o estado corrente de cada bronze
append-only, por onde o tratamento lê — ficam fora, com as leituras
creditadas à tabela que elas espelham.

### `cru` — bronze: o que a fonte disse. NUNCA SE DROPA

| objeto | tipo | política declarada | DDL | escrito por | lido por |
|---|---|---|---|---|---|
| `cru.cinema` | table | nao se dropa, mas e a UNICA bronze com PODA por desenho — dias que ficaram no passado saem na raspagem. | [sql/cru/cinema.sql](../../sql/cru/cinema.sql) | `coleta/gravar.py` | `tratamento/cinema.py` |
| `cru.ingresse` | table | NUNCA SE DROPA e APPEND-ONLY. | [sql/cru/ingresse.sql](../../sql/cru/ingresse.sql) | `coleta/gravar.py` | `tratamento/comum.py` |
| `cru.instagram` | table | NUNCA SE DROPA. | [sql/cru/instagram.sql](../../sql/cru/instagram.sql) | `coleta/gravar.py` | `tratamento/instagram.py`, `pipeline/atualizar.py` |
| `cru.shotgun` | table | NUNCA SE DROPA e APPEND-ONLY. | [sql/cru/shotgun.sql](../../sql/cru/shotgun.sql) | `coleta/gravar.py` | `tratamento/comum.py` |
| `cru.sympla` | table | NUNCA SE DROPA e APPEND-ONLY. | [sql/cru/sympla.sql](../../sql/cru/sympla.sql) | `coleta/gravar.py` | `tratamento/comum.py` |
| `cru.ticketandgo` | table | NUNCA SE DROPA e APPEND-ONLY. | [sql/cru/ticketandgo.sql](../../sql/cru/ticketandgo.sql) | `coleta/gravar.py` | `tratamento/comum.py` |
| `cru.tmdb` | table | NUNCA SE DROPA, ACUMULATIVA e fora do snapshot de proposito — tratado.filmes/sessoes sao reconstruidas do zero a cada rodada, e o enriquecimento nao p… | [sql/cru/tmdb.sql](../../sql/cru/tmdb.sql) | `coleta/gravar.py` | `tratamento/cinema.py`, `pipeline/atualizar.py` |
| `cru.zig` | table | NUNCA SE DROPA e APPEND-ONLY. | [sql/cru/zig.sql](../../sql/cru/zig.sql) | `coleta/gravar.py` | `tratamento/comum.py` |
| `cru.inventario` | view | — | [sql/cru/zz_views.sql](../../sql/cru/zz_views.sql) | — | `pipeline/atualizar.py` |

### `tratado` — prata: o schema unificado. Descartável por desenho

| objeto | tipo | política declarada | DDL | escrito por | lido por |
|---|---|---|---|---|---|
| `tratado.eventos` | table | descartavel POR DESENHO — tem que se reconstruir a seco a partir do cru. | [sql/tratado/eventos.sql](../../sql/tratado/eventos.sql) | `tratamento/busca.py`, `tratamento/comum.py`, `tratamento/curadoria.py`, `tratamento/enriquecer.py`, `tratamento/instagram.py`, `tratamento/sumido.py`, `ferramentas/linhagem.py` | `tratamento/slug.py`, `pipeline/atualizar.py`, `ferramentas/curar.py` |
| `tratado.filmes` | table | 100% descartavel — derivar.aplicar_cinema reconstroi filmes e sessoes do zero a partir do cru a cada rodada (SNAPSHOT). | [sql/tratado/filmes.sql](../../sql/tratado/filmes.sql) | `tratamento/busca.py`, `tratamento/cinema.py` | `tratamento/slug.py`, `pipeline/atualizar.py` |
| `tratado.lotes` | table | 100% descartavel e ja e reconstruida do zero a cada aplicar() (DELETE + INSERT — por isso sem PK natural). | [sql/tratado/lotes.sql](../../sql/tratado/lotes.sql) | `tratamento/comum.py`, `tratamento/instagram.py` | — |
| `tratado.sessoes` | table | 100% descartavel. | [sql/tratado/sessoes.sql](../../sql/tratado/sessoes.sql) | `tratamento/cinema.py` | — |

### `curado` — o que uma PESSOA decidiu. NUNCA SE DROPA

| objeto | tipo | política declarada | DDL | escrito por | lido por |
|---|---|---|---|---|---|
| `curado.correcoes` | table | NUNCA SE DROPA e APPEND-ONLY. | [sql/curado/correcoes.sql](../../sql/curado/correcoes.sql) | `ferramentas/curar.py` | `tratamento/curadoria.py` |
| `curado.locais` | table | NUNCA SE DROPA. | [sql/curado/locais.sql](../../sql/curado/locais.sql) | `ferramentas/curar.py` | `tratamento/curadoria.py` |
| `curado.pendencias` | view | — | [sql/curado/zz_pendencias.sql](../../sql/curado/zz_pendencias.sql) | — | `tratamento/curadoria.py` |

### `operacao` — telemetria e artefatos nossos. NUNCA SE DROPA

| objeto | tipo | política declarada | DDL | escrito por | lido por |
|---|---|---|---|---|---|
| `operacao.coletas` | table | NUNCA SE DROPA. | [sql/operacao/coletas.sql](../../sql/operacao/coletas.sql) | `pipeline/execucoes.py` | `tratamento/sumido.py` |
| `operacao.execucoes` | table | NUNCA SE DROPA. | [sql/operacao/execucoes.sql](../../sql/operacao/execucoes.sql) | `pipeline/execucoes.py` | `pipeline/atualizar.py` |
| `operacao.midias` | table | NUNCA SE DROPA. | [sql/operacao/midias.sql](../../sql/operacao/midias.sql) | `coleta/gravar.py` | `tratamento/cinema.py`, `tratamento/instagram.py`, `pipeline/atualizar.py` |
| `operacao.slugs` | table | append-only por `slug` — o slug e a chave, entao um endereco nunca "muda de dono" por acidente. | [sql/operacao/slugs.sql](../../sql/operacao/slugs.sql) | `tratamento/slug.py` | — |

### `uso` — quem usou (LGPD). NUNCA SE DROPA

| objeto | tipo | política declarada | DDL | escrito por | lido por |
|---|---|---|---|---|---|
| `uso.acessos` | table | NUNCA SE DROPA; LGPD. | [sql/uso/acessos.sql](../../sql/uso/acessos.sql) | `servico/mcp_server.py` | — |
| `uso.feedback` | table | NUNCA SE DROPA; LGPD. | [sql/uso/feedback.sql](../../sql/uso/feedback.sql) | `servico/feedback.py` | — |
| `uso.usuarios` | table | NUNCA SE DROPA; LGPD. | [sql/uso/usuarios.sql](../../sql/uso/usuarios.sql) | `servico/mcp_server.py` | — |

### `public` — só views: o contrato de consumo

| objeto | tipo | política declarada | DDL | escrito por | lido por |
|---|---|---|---|---|---|
| `public.eventos` | view | — | [sql/public/eventos.sql](../../sql/public/eventos.sql) | — | `servico/consulta.py` |
| `public.filmes` | view | — | [sql/public/filmes.sql](../../sql/public/filmes.sql) | — | `servico/consulta.py` |
| `public.lotes` | view | — | [sql/public/lotes.sql](../../sql/public/lotes.sql) | — | `servico/consulta.py` |
| `public.sessoes` | view | — | [sql/public/sessoes.sql](../../sql/public/sessoes.sql) | — | `servico/consulta.py` |
| `public.slugs_antigos` | view | — | [sql/public/slugs_antigos.sql](../../sql/public/slugs_antigos.sql) | — | `servico/consulta.py` |

## 9. Portas de consumo

Quem lê `public` pela camada canônica (`servico/consulta.py`):

- `api/dados.py`
- `src/servico/mcp_server.py`
