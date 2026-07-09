# Spec — MVP Fase 0 (núcleo): cobertura, ruído, dedupe e fluxo sob demanda

> **Status:** Etapas 1–4 **executadas** em 2026-07-09 (ver [`execucao.md`](execucao.md));
> **Etapa 5 adicionada na revisão de 2026-07-09** (campos ricos da fonte — §5.7),
> pendente de execução. Escopo e decisões fechados com o autor.
> **O quê/por quê:** `docs/PRD_MVP.md`, seção 6 (Fase 0). Esta spec é o **como**.
> **Critério de sucesso da fase (PRD):** o autor abre o agente em vez do Sympla
> para saber "o que tem hoje em Brasília" — e confia na resposta.

---

## 1. Objetivo

Deixar o pipeline local (raspar → base SQLite → MCP) bom o suficiente para
dogfooding diário. Cinco entregas:

1. **Cobertura/qualidade da raspagem** das 3 fontes (Sympla, Ingresse, Shotgun),
   com medição de cobertura contra o total reportado por cada fonte.
2. **Filtro de ruído v1** (regras por palavra-chave): anúncios/cursos que o
   `themes=99` do Sympla deixa passar são **marcados** e somem da consulta.
3. **Dedupe cross-fonte v1** (regras): o mesmo evento em duas plataformas é
   **agrupado** e a consulta devolve um registro só.
4. **Fluxo sob demanda:** um entrypoint dedicado `src/atualizar.py` que roda tudo
   e imprime um relatório de saúde da base.
5. **Campos ricos da fonte** (adicionada na revisão de 2026-07-09): sondar e
   capturar **descrição** e demais campos que as fontes oferecem e hoje são
   descartados (line-up, preço, organizador do Shotgun) — ver §5.6.

## 2. Decisões já tomadas (não rediscutir)

Fechadas com o autor em 2026-07-09:

- **Escopo = só o núcleo** (festas/baladas/shows). Cinema, Instagram, gênero por
  LLM e até gênero por palavras-chave ficam **fora** — cada um vira spec própria.
- **Marcar, não apagar.** Ruído e duplicata continuam na base, com colunas de
  marcação; quem filtra/colapsa é a camada de consulta. Auditável e re-executável
  sem re-raspar.
- **Entrypoint novo `src/atualizar.py`** para o "rodar na mão". `demo.py` fica
  como demo/registro da PoC.
- Herdadas do PRD (§7): SQLite local, sem nuvem, sem GitHub Actions, sem LLM na
  ingestão, cadência sob demanda, Brasília-only, schema cidade-aware.

## 3. Diagnóstico do estado atual (medido em 2026-07-09)

Base `data/eventos.db` com 315 eventos: 289 Sympla, 22 Shotgun, 4 Ingresse.

- **`categoria` é inútil para filtrar ruído no Sympla:** `event_type` veio
  `'NORMAL'` em 100% dos 289 eventos. O filtro v1 terá que operar sobre o
  **nome** (e vale investigar se a API entrega campos de tema/categoria mais
  ricos ao pedi-los em `only`).
- **Ruído confirmado na base:** ex. *"Conecte-se com a Melhor Banda Larga
  Residencial em Brasília"* (anúncio). `docs/PROXIMOS_PASSOS.md` registra também
  cursos e conferências em coletas anteriores.
- **Horizonte do Shotgun é curtíssimo:** eventos futuros só até 2026-07-12
  (3 dias), contra novembro/dezembro nas outras fontes. Suspeita: a página da
  cidade só lista os próximos eventos e/ou o scroll fixo (3 rolagens,
  `max_eventos=40`) trunca a lista. É o principal problema de cobertura.
- **Ingresse tem só 4 eventos.** Conferir no site se o catálogo de Brasília é
  realmente esse (o módulo já pagina até `total_pages`; provável que sim).
- **Duplicatas cross-fonte existem e o matching ingênuo erra:** por interseção
  de tokens, *"Sambinha da Copa - 05/07"* ~ *"05/07 Samba Da Passarinha (Oitavas
  De Final...)"* aparece junto do falso-positivo *"Varanda da Copa | Oitavas de
  Final..."* ~ *"Samba Da Passarinha"* (casam por "Oitavas de Final"). O dedupe
  precisa de âncora além do nome (local e data) e de política conservadora.
- **Dívida menor:** `demo.py::consultar()` duplica a lógica de `consulta.py`
  comparando `start_date` como string crua — exatamente a armadilha documentada
  no `CLAUDE.md`.

## 4. Fora de escopo

Cinema (Cinemark/Kinoplex), Instagram, classificação de gênero (por LLM **ou**
por palavra-chave), Postgres/Neon, GitHub Actions, MCP remoto, páginas públicas,
instrumentação de uso, outras cidades. Nada disso entra nesta spec.

## 5. Design

### 5.1 Schema (`sql/schema.sql`)

Novas colunas em `eventos`, todas preenchidas pelo enriquecimento v1 (nunca
pelos scrapers — eles seguem ignorando esses campos):

```sql
ruido          INTEGER NOT NULL DEFAULT 0,  -- 1 = não é vida noturna (anúncio/curso/etc.), some da consulta
ruido_motivo   TEXT,                        -- regra que marcou (ex.: a palavra-chave), p/ auditoria
dedupe_grupo   TEXT,                        -- id do grupo de duplicatas = id do evento canônico; NULL = sem duplicata
dedupe_canonico INTEGER NOT NULL DEFAULT 1  -- 1 = registro que representa o grupo na consulta
```

**Migração:** nenhuma. Na Fase 0 a base é descartável (gitignorada, regenerável
em minutos): ao mudar o schema, **apagar `data/eventos.db` e re-raspar**. Isso
evita lógica de `ALTER TABLE` e o risco de `conectar()` (que só roda
`IF NOT EXISTS`) abrir uma base velha sem as colunas novas. Documentar esse
comportamento no relatório do `atualizar.py` se detectar base antiga (checar via
`PRAGMA table_info(eventos)` e falhar com mensagem clara mandando apagar o
arquivo).

O upsert em `store.py` **não** inclui as colunas novas (assim uma re-raspagem
não zera marcações; de todo modo elas são recalculadas a cada `atualizar.py`).

### 5.2 Enriquecimento v1 — módulo novo `src/enriquecer.py`

Roda **depois** do upsert, sobre a base inteira (centenas de linhas — custo
irrelevante). **Idempotente e recalculado do zero a cada execução**: primeiro
reseta as 4 colunas, depois reaplica as regras. Mudou uma regra → basta rodar de
novo, sem re-raspar.

API do módulo:

```python
def aplicar(con) -> dict:   # orquestra: reset → marcar_ruido → agrupar_duplicatas
    ...                     # retorna contadores p/ o relatório do atualizar.py
```

**Normalização de texto** (helper compartilhado): minúsculas, remoção de acentos
(`unicodedata.normalize("NFKD")` + descarte de combining), remoção de pontuação,
colapso de espaços. Usada tanto no ruído quanto no dedupe.

**Ruído (regras por palavra-chave):**

- Lista inicial de termos (casados por **fronteira de palavra** sobre o nome
  normalizado, para "curso" não pegar "percurso"): `curso`, `workshop`,
  `congresso`, `conferencia`, `seminario`, `simposio`, `palestra`, `imersao`,
  `treinamento`, `mentoria`, `aula`, `mba`, `pos graduacao`, `webinar`,
  `banda larga`, `consorcio`, `credito`, `investimento`.
- A lista vive como constante em `enriquecer.py` (não em arquivo de config —
  YAGNI na Fase 0) e **deve ser calibrada durante a implementação**: rodar sobre
  a base real, listar todos os marcados e conferir a olho que nenhum evento real
  de vida noturna foi pego (ex.: cuidado com "aula" em "aulão de dança"? —
  fronteira de palavra pega "aula" mas não "aulão"; conferir caso a caso).
- Marca `ruido=1` e `ruido_motivo=<termo>`. Na dúvida, **não marcar** (falso
  negativo é ruído tolerável; falso positivo esconde festa de verdade).

**Dedupe cross-fonte (regras conservadoras):**

1. Candidatos: pares de eventos de **fontes diferentes**, **não-ruído**, com
   `start_date` no **mesmo dia** (data extraída do timestamp normalizado via a
   mesma lógica do `_norm_ts` de `consulta.py` — formatos mistos, ver CLAUDE.md).
2. Um par é duplicata se:
   - similaridade de nome **≥ 0.85** (`difflib.SequenceMatcher.ratio()` sobre
     nomes normalizados), **ou**
   - similaridade de nome **≥ 0.55 e** mesmo local (`local_nome` normalizado
     igual e não-vazio).
   Os limiares são ponto de partida — **calibrar na implementação** contra os
   pares reais da base (o par "Sambinha da Copa" deve agrupar; o falso-positivo
   "Varanda da Copa" ~ "Samba da Passarinha" não pode agrupar).
   Antes de comparar, remover do nome normalizado padrões de data (`05 07`,
   `05/07`...), que inflam a similaridade entre eventos distintos do mesmo dia.
3. Grupos = fecho transitivo dos pares (union-find simples).
4. **Canônico** do grupo: o registro com mais campos preenchidos entre
   `endereco, local_nome, organizador, imagem, end_date, lat`; empate → ordem de
   fonte `sympla > shotgun > ingresse` (Sympla costuma trazer mais metadados).
   Membros recebem `dedupe_grupo=<id do canônico>`; só o canônico fica com
   `dedupe_canonico=1`.
5. Política: **na dúvida, não agrupar.** Evento sumir da resposta por dedupe
   errado é pior do que aparecer duas vezes.

### 5.3 Consulta (`src/consulta.py`)

`buscar_eventos` passa a filtrar por padrão:

```sql
WHERE e.ruido = 0 AND e.dedupe_canonico = 1
```

- Novo campo no retorno: `outras_urls` — subselect com
  `GROUP_CONCAT(url)` dos **outros** membros do grupo (NULL se não há grupo).
  Materializa o valor do dedupe: uma resposta só, com o link das duas
  plataformas.
- Novo parâmetro opcional `incluir_ruido=False` (depuração; não exposto na tool
  MCP).
- `src/mcp_server.py` não muda de assinatura — segue delegação fina. Atualizar
  apenas a docstring da tool se o retorno ganhar `outras_urls` (a docstring é o
  contrato que o agente lê).

### 5.4 Cobertura por fonte

Cada scraper ganha a noção de **cobertura medida**: `raspar(...)` passa a
retornar também o total reportado pela fonte (ou o módulo expõe isso de outra
forma simples), e o `atualizar.py` imprime `coletados/total` por fonte.

- **Sympla** (`src/scrapers/sympla.py`):
  - Descobrir se a paginação com `sort=month-trending-score` esgota o catálogo:
    comparar acumulado vs `total` da resposta. Se truncar, testar outros `sort`
    (ex.: por data) ou paginar sem sort.
  - Subir `max_paginas` até esgotar (`len(data) < limit` já encerra o loop —
    o custo de um teto alto é zero quando o catálogo é menor).
  - Investigar campos extras no `only` (tema/categoria/descrição curta) que
    ajudem o filtro de ruído; hoje `event_type` é constante `'NORMAL'`. Se
    existir um campo de tema real, adicioná-lo ao `only` e gravá-lo em
    `categoria` (o schema não muda).
- **Ingresse** (`src/scrapers/ingresse.py`): já pagina até `total_pages`.
  Validar manualmente (site aberto vs base) que os ~4 eventos são o catálogo
  real de Brasília. Se o site mostrar mais, investigar parâmetros do
  `/events/search` via `/openapi.json` (categorias? flag de "somente
  destacados"?).
- **Shotgun** (`src/scrapers/shotgun.py`) — **prioridade da frente de
  cobertura**, horizonte de 3 dias é inaceitável:
  - Trocar o scroll fixo (3×) por **scroll até estabilizar**: rolar enquanto o
    conjunto de slugs crescer (com teto de segurança, ex. 30 rolagens).
  - Procurar na página da cidade um botão/link "ver mais"/paginação e seções
    além do "em alta"; clicar/esgotar se existir.
  - Subir `max_eventos` (teto de segurança alto, ex. 200), mantendo ritmo
    educado entre páginas de evento (o site já respondeu 429 a HTTP puro).
  - Se mesmo assim o horizonte ficar curto, investigar rotas alternativas do
    site (ex. sitemap, página "all events") **antes** de aceitar a limitação —
    e, se for limitação real da fonte, registrar no relatório e no
    `docs/PROXIMOS_PASSOS.md`.
- Links **relativos** no Shotgun: a regex de slugs continua casando path
  relativo (armadilha documentada no CLAUDE.md — não "consertar").

### 5.5 Entrypoint `src/atualizar.py`

O comando único da Fase 0. Fluxo:

```
raspar (3 fontes, tolerante a falha por fonte)
  → store.upsert_eventos
  → enriquecer.aplicar          (ruído + dedupe, recalculado do zero)
  → store.reconstruir_fts
  → relatório
```

- **Flags:** `--sem-shotgun` (pula o navegador) e `--so-enriquecer` (não raspa;
  reaplica regras + FTS + relatório — para iterar regra sem esperar raspagem).
- **Tolerância a falha:** exceção num scraper não derruba o pipeline — loga o
  erro, segue com as outras fontes e o relatório destaca a fonte que falhou.
  Sai com código ≠ 0 se **todas** as fontes falharem.
- **Relatório final** (o "painel de saúde" que o autor olha antes de perguntar
  ao agente): por fonte — coletados/total do site e falhas; base — total,
  futuros, marcados como ruído (com amostra dos nomes), grupos de dedupe (com os
  pares), janela de datas futura por fonte (min/max de `start_date`), duração da
  execução.
- Convenções existentes: rodar da raiz (`python src/atualizar.py`), imports
  irmãos (`import store`, `import enriquecer`, `from scrapers import ...`),
  prints em português, sem dependência nova.

### 5.6 Campos ricos da fonte — Etapa 5 (revisão de 2026-07-09)

Motivação (dogfooding de 2026-07-09): a busca por "eletrônico" só achou eventos com o
gênero **no nome**, enquanto a descrição do "VÉRTICE - House" no Sympla diz
literalmente *"cena eletrônica de Brasília"*. Hoje **nenhum scraper captura descrição**
(o schema nem tem coluna) e o Shotgun joga fora campos que já chegam prontos.

**Sondagem já realizada (2026-07-09):**

| Fonte | Catálogo | Página do evento |
|---|---|---|
| Shotgun | — | JSON-LD **já lido** tem `description`, `performer` (line-up), `organizer`, `doorTime`, `offers` — tudo descartado hoje |
| Sympla | sem descrição (objeto completo da API conferido, sem `only`) | descrição rica no estado Next.js (campo `detail`, HTML); urllib toma loop de redirect, Playwright abre |
| Ingresse | sem descrição (chaves: title/place/session/poster/slug) | **não sondada** — o BFF expõe `/openapi.json`; procurar endpoint de evento individual |

**Sondagem restante (primeiro passo da etapa):**
- Sympla: caçar um **endpoint JSON do evento individual** com a técnica do
  `discover_sympla.py` na página de evento — HTML/Playwright só como último recurso.
- Ingresse: inventariar o `/openapi.json` (endpoint de evento por id/slug) e conferir
  quais campos a página entrega.
- Inventariar na mesma passada **qualquer outro campo aproveitável** (preço, line-up,
  classificação etária, porta/horário), não só descrição.

**Schema (colunas novas em `sql/schema.sql`, preenchidas pelos scrapers):**

```sql
descricao   TEXT,   -- texto livre do evento (limpo de HTML); insumo do FTS e do enriquecimento v2
atracoes    TEXT,   -- line-up ("; "-separado) quando a fonte entrega (Shotgun: performer)
preco_min   REAL    -- menor preço anunciado, quando a fonte entrega (Shotgun: offers)
```

Migração: mesma política do §5.1 — base descartável, apagar e re-raspar. De quebra,
**preencher `organizador`** no Shotgun (coluna já existe; `ld["organizer"]` está
disponível e hoje vira `NULL`).

**Captura por fonte:**
- **Shotgun:** direto no `_normalizar` (custo zero — a página já é visitada).
- **Sympla/Ingresse:** conforme a sondagem. Se exigir uma requisição por evento,
  fazer como **passo incremental** do `atualizar.py`: só busca eventos **novos/sem
  descrição** (nunca re-buscar o que já tem), com ritmo educado e teto por execução.
  Importante: descrição colhida por passo próprio **não pode ser zerada pelo upsert**
  do catálogo — ou a coluna fica fora da lista do upsert, ou o passo roda depois
  (decidir na implementação; testar re-raspagem sem perda).
- Limpar HTML para texto puro antes de gravar (a descrição alimenta FTS e LLM).

**FTS e consulta:**
- Avaliar incluir `descricao` no `eventos_fts` (**testar antes de ligar**: descrição
  menciona gêneros de passagem — medir precisão nas consultas canônicas com e sem;
  se ligar, considerar peso menor via `bm25()` por coluna). O caso de aceite: a busca
  "eletrônica OR eletrônico" deve passar a achar o Vértice.
- Expor `descricao` (truncada?) e `atracoes` no retorno de `buscar_eventos` — decidir
  na implementação o tamanho (o retorno vai para o contexto do agente; descrição
  inteira de 250 eventos é peso morto — talvez só um trecho, ou campo completo apenas
  quando `limite` for pequeno).

### 5.7 Ajustes menores

- `src/demo.py`: `consultar()` passa a delegar para `consulta.buscar_eventos`
  (elimina a comparação de data como string crua). O arquivo permanece como
  demo da PoC.
- `docs/PROXIMOS_PASSOS.md`: ao final da execução, atualizar os itens cobertos
  por esta spec (filtro/dedupe/cobertura saem do backlog ou mudam de estado).

## 6. Testes e verificação

Seguir o padrão do repo: **scripts executáveis, sem framework**.

- **Novo `tests/test_enriquecer.py`** (roda com `python tests/test_enriquecer.py`,
  base `sqlite3` em memória + `sql/schema.sql`):
  - ruído: nome com "curso" marca; "percurso"/"aulão" não marca; acentos não
    importam ("imersão" ↔ "imersao").
  - dedupe: par sintético mesmo-dia+mesmo-local+nome parecido agrupa; par
    "Varanda da Copa" vs "Samba da Passarinha" (o falso-positivo real) **não**
    agrupa; canônico escolhido pela regra de campos preenchidos; idempotência
    (rodar `aplicar` 2× = mesmo resultado).
  - consulta: `buscar_eventos` não devolve ruído nem membros não-canônicos;
    `outras_urls` traz a URL do membro colapsado.
- **`tests/test_mcp_server.py`** continua passando (é o smoke do caminho real).
  Adicionar um assert de que nenhum resultado devolvido tem nome casando com a
  lista de ruído.
- **Verificação manual instrumentada** (parte da execução, não do usuário):
  rodar `python src/atualizar.py` ponta a ponta e conferir o relatório contra
  os sites (amostragem: abrir Sympla/Shotgun e comparar contagens e 2–3 eventos
  específicos).

## 7. Critérios de aceite (binários, autoverificáveis)

1. `python src/atualizar.py` roda ponta a ponta sem erro e imprime o relatório
   completo (numa base recém-apagada, inclusive).
2. O anúncio de banda larga (e qualquer curso/conferência coletado) está com
   `ruido=1` na base e **não aparece** em `buscar_eventos`.
3. Zero falso-positivo de ruído na base real: a lista completa de marcados foi
   revisada e só contém não-eventos (a revisão fica registrada no resumo final
   para o autor conferir).
4. Duplicatas cross-fonte reais da base agrupadas; o falso-positivo conhecido
   não agrupado; membros não-canônicos fora da consulta e presentes em
   `outras_urls` do canônico.
5. Cobertura Sympla e Ingresse: coletado ≥ 95% do total reportado pela fonte
   (descontando eventos passados). Shotgun: horizonte de datas futuro claramente
   maior que os 3 dias atuais **ou** evidência documentada de que a fonte não
   expõe mais que isso.
6. `python tests/test_enriquecer.py` e `python tests/test_mcp_server.py` passam.
7. `python src/atualizar.py --so-enriquecer` re-marca a base sem raspar.
8. Nenhuma consulta compara `start_date` como string crua (o `demo.py` foi
   ajustado).

Da Etapa 5 (revisão de 2026-07-09):

9. Todo evento do Shotgun cuja página tem `description`/`performer`/`organizer` no
   JSON-LD grava `descricao`/`atracoes`/`organizador` (e `preco_min` quando `offers`
   trouxer preço); o relatório do `atualizar.py` mostra o **% de eventos com
   descrição por fonte**.
10. A sondagem de Sympla e Ingresse está documentada (em `execucao.md`) com a
    decisão tomada: endpoint JSON encontrado, ou fallback definido (Playwright
    incremental), ou "fonte não expõe" — e, no que for viável, implementada.
11. Re-raspagem do catálogo **não zera** descrição já colhida (testado).
12. Se `descricao` entrar no FTS: a busca "eletrônica OR eletrônico" acha o caso
    real (VÉRTICE - House, ou equivalente vivo na base) **sem** degradar as
    consultas canônicas de gênero; se ficar fora, o motivo está registrado.

## 8. Plano de execução (pensado para autonomia)

Intervenção do usuário: **nenhuma configuração externa é necessária** (tudo
local, sem credenciais). O usuário entra só na revisão final e nos commits
(convenção do repo: **ele** dispara os commits, em partes lógicas — ao final,
apresentar uma sugestão de fatiamento dos commits, sem executá-los).

- **Etapa 1 — Enriquecimento:** colunas no `sql/schema.sql` + `src/enriquecer.py`
  + `tests/test_enriquecer.py`. Verificação: teste novo passa; `--so-enriquecer`
  (pode ser implementado já aqui junto de um esqueleto do `atualizar.py`) marca
  a base real e a lista de marcados é revisada (critérios 2–3).
- **Etapa 2 — Consulta:** filtros default + `outras_urls` em `consulta.py`;
  docstring da tool MCP. Verificação: `python src/consulta.py` e
  `python tests/test_mcp_server.py`.
- **Etapa 3 — Cobertura:** investigação e correção fonte a fonte (Shotgun
  primeiro), medição coletado/total. Verificação: critério 5, comparando com os
  sites.
- **Etapa 4 — Integração:** `atualizar.py` completo (flags, tolerância a falha,
  relatório), ajuste do `demo.py`, atualização do `PROXIMOS_PASSOS.md`, base
  recriada do zero, todos os critérios do §7 re-checados, resumo final para
  revisão do autor (incluindo a lista de ruído marcada e os grupos de dedupe).
- **Etapa 5 — Campos ricos** (adicionada na revisão de 2026-07-09; etapas 1–4 já
  executadas): (a) concluir a sondagem (endpoint de evento individual no Sympla e
  no Ingresse, inventário de campos extras); (b) colunas `descricao`/`atracoes`/
  `preco_min` no schema + captura no Shotgun (JSON-LD, custo zero) e nas demais
  fontes conforme a sondagem, incremental quando custar 1 requisição/evento;
  (c) decisão medida sobre `descricao` no FTS + exposição na consulta/tool;
  (d) base recriada, critérios 9–12 checados, `execucao.md` atualizado com a
  calibração. Absorve os itens `NI-02`/`NI-03` do backlog (saem da lista ao
  concluir).

Depois da revisão, começa o que a spec **não** cobre: o dogfooding em si — usar
o agente por algumas semanas e deixar o critério do PRD decidir se a Fase 0
fechou.

## 9. Riscos e casos de borda

- **APIs internas mudam sem aviso** (risco nº 1 do produto). Se uma fonte
  quebrar durante a execução: `discover_sympla.py` é a ferramenta de
  reconhecimento; a tolerância a falha do `atualizar.py` impede que uma fonte
  quebrada esconda as outras.
- **429 no Shotgun:** manter Playwright, ritmo educado, e não paralelizar a
  leitura das páginas de evento.
- **Falso-positivo de dedupe/ruído** esconde evento real — por isso as políticas
  conservadoras (§5.2) e a revisão da lista completa (§7.3).
- **Datas em formatos mistos** (Sympla/Ingresse `+00:00` × Shotgun `.000Z`):
  toda comparação de data no enriquecimento usa a normalização do `_norm_ts` —
  nunca string crua.
- **Dia do evento e fuso:** agrupar por "mesmo dia" usando o dia em UTC pode
  divergir do dia local (festa de sábado 23h em Brasília = domingo 02h UTC).
  Para o pareamento isso é inócuo (ambas as fontes sofrem o mesmo desvio), mas
  se aparecer par real com dias UTC distintos, ampliar o candidato para
  "diferença ≤ 6h" em vez de mesmo dia-calendário.
- **FTS e marcações:** o índice FTS indexa `nome`/`categoria`; ruído/dedupe são
  filtrados por `WHERE`, não pelo índice — `reconstruir_fts` segue igual.
- **Base velha sem as colunas novas:** falhar cedo com mensagem clara
  ("apague data/eventos.db e rode de novo") — ver §5.1.

## 10. Referências

- `docs/PRD_MVP.md` §6 (Fase 0), §7 (decisões travadas), §8 (riscos).
- `docs/PROXIMOS_PASSOS.md` itens 2 e 3 (ruído/gênero, cobertura) — gênero fica
  fora (decisão §2).
- `CLAUDE.md` — convenções (imports irmãos, datas mistas, links relativos do
  Shotgun, estratégia de commit).
