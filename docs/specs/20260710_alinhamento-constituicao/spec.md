# Spec — Alinhamento à Constituição: observabilidade da rodada, evento sumido, utilitários únicos e janela do precificar (NI-19)

> **Status:** especificada em 2026-07-10 (implementação na sequência, mesmo dia).
> **O quê/por quê:** leitura da Constituição de Engenharia de Dados do CFOx
> (`CFOx/Programa/pipeline_cfox/docs/constituicao.md`, v1) contra este projeto.
> Valores já bem atendidos aqui: transformação como fim (valor 1), seleção/
> deleção (valor 2, `rejeitado.yaml`), documentação (valor 6) e eficiência
> (valor 8). Quatro lacunas viram as quatro partes desta spec:
> observabilidade (valor 4), corretude (valor 3), sustentabilidade (valor 5)
> e velocidade (valor 7). A parte 1 é a que mais paga: protege a hipótese de
> risco nº 1 do produto (a raspagem quebrar sem ninguém perceber).

---

## 1. Observabilidade — tabela `execucoes` (valor 4)

Hoje o relatório de saúde do `atualizar.py` é `print()` efêmero: fechou o
terminal, a rodada não deixou rastro. Se o Sympla mudar a API e a coleta cair
de ~290 para 12, não há rodada anterior para comparar. E `_descrever`/
`_precificar` engolem exceção num contador (`falhas += 1`) sem registrar qual
evento falhou nem por quê — um padrão sistemático (todos os Ingresse com 403)
fica invisível.

### 1.1 DDL (nova no `sql/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS execucoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciada_em TEXT NOT NULL,   -- ISO 8601 UTC do início da rodada
    duracao_s   REAL,            -- duração total em segundos
    modo        TEXT NOT NULL,   -- completo | sem-shotgun | so-derivar | so-enriquecer
    fontes      TEXT,            -- JSON {fonte: {coletados, total_site} | {erro}}
    passos      TEXT,            -- JSON {descrever: {...}, precificar: {...}, derivado: {...}, ruido: N, dedupe_grupos: N, sumidos: N}
    erros       TEXT             -- JSON [{passo, evento_id, erro}] — falha POR EVENTO
);
```

Campos compostos como **JSON em colunas TEXT**, de propósito: modelar
`execucao_fontes`/`execucao_erros` como tabelas relacionais seria custo de
schema sem consulta que o justifique (valores 2 e 8). Quem lê isso é gente
depurando (DBeaver) e o próprio relatório da rodada seguinte.

### 1.2 Comportamento

- `store.registrar_execucao(con, dados)` grava a linha ao fim do `main()`;
  `store.ultima_execucao(con)` devolve a mais recente (para a comparação).
- `_descrever`/`_precificar` passam a acumular `{passo, evento_id, erro}` numa
  lista compartilhada (o `print` de progresso continua igual). Descarte por
  nome divergente (guarda NI-17) também entra na lista, com motivo próprio.
- O relatório ganha o bloco **"vs. rodada anterior"**: para cada fonte raspada
  agora e na última execução com coleta daquela fonte, imprime
  `sympla 287 → 61` e, se a queda passar de **50%**, um alerta explícito
  (`*** ALERTA: queda de N% — scraper quebrado?`). Limiar constante no código
  (`QUEDA_ALERTA = 0.5`), não configurável — calibrar depois se der falso
  positivo.
- Toda rodada grava execução, inclusive `--so-derivar`/`--so-enriquecer`
  (coluna `modo` distingue); a comparação de coleta só considera execuções em
  que a fonte foi de fato raspada.

## 2. Corretude — evento sumido da fonte (valor 3)

O upsert nunca remove nada. Evento **futuro** que a fonte tirou do ar
(cancelamento silencioso, remoção) fica órfão na base respondendo consultas.
O `cancelado` derivado da Bronze só cobre quando o payload diz `cancelled` —
não cobre o evento que simplesmente desaparece do catálogo.

**Decisão de modelagem: não criar `visto_em`.** A primeira versão desta
proposta previa uma coluna nova, mas `raspado_em` **já tem essa semântica**:
só o upsert do catálogo o atualiza (o "descrever"/"precificar" mexem em outras
colunas), logo `raspado_em` = "última vez que o evento apareceu na raspagem do
catálogo". Duplicar isso violaria o valor 8. O comentário do schema passa a
travar essa semântica ("âncora do sumido — não atualizar fora do upsert").

### 2.1 Coluna nova + marcação

```sql
    sumido INTEGER NOT NULL DEFAULT 0  -- 1 = evento FUTURO que não reapareceu na última raspagem bem-sucedida da sua fonte
```

Após `_raspar`, um passo novo `_marcar_sumidos(con, resultados, inicio)`:

- Só para fontes **raspadas sem erro nesta rodada** — fonte que falhou não
  condena seus eventos (senão um 500 do Sympla esconderia a agenda inteira).
- Para cada evento da fonte: `sumido = 1` se `start_date` é futuro **e**
  `raspado_em < início da rodada`; senão `sumido = 0` (recálculo do zero,
  idempotente como derivar/enriquecer — evento que reaparece é desmarcado).
- Evento **passado** nunca é marcado: catálogo só lista futuros, então todo
  evento realizado "some" da fonte naturalmente — marcá-lo esconderia o
  histórico da consulta sem ganho.
- `--so-derivar`/`--so-enriquecer` não tocam em `sumido` (não houve raspagem).

### 2.2 Consulta e relatório

- `buscar_eventos` esconde `sumido = 1` por padrão, no mesmo grupo de
  `ruido`/`cancelado` (`incluir_ruido=True` mostra, para depuração). Marcar,
  não apagar — filosofia já estabelecida.
- `detalhar_evento` **não** filtra: se o agente tem a URL na mão, responder é
  mais útil que sumir (mesmo racional do esgotado).
- O relatório lista os sumidos da rodada (nome + fonte), para calibração — se
  aparecer festa real aí, o mecanismo está errado e a lista denuncia.

### 2.3 Risco aceito

Raspagem de catálogo parcial (ex.: paginação interrompida sem exceção)
marcaria sumidos em massa por engano. Mitigação: o alerta de queda da parte 1
dispara no mesmo cenário (coletados despenca), e a lista nominal no relatório
expõe o estrago antes de virar crise. Não adicionamos trava automática
(ex.: "não marcar se coletados < X% do total") — complexidade especulativa.

## 3. Sustentabilidade — utilitários únicos (valor 5)

A pegadinha mais documentada do projeto (datas ISO em formatos mistos) tem a
mesma solução escrita três vezes: `_instante` em `atualizar.py`, `_instante`
em `enriquecer.py` e `_norm_ts` em `consulta.py`. Um quarto formato de data
exigiria lembrar de três lugares.

- **`src/tempo.py` (módulo novo, ~25 linhas):** `instante(iso) -> datetime UTC
  | None` e `norm_ts(iso) -> str ISO UTC | None` (este continua registrado
  como função SQL pela `consulta.py`). Os três módulos importam daqui;
  as cópias locais somem.
- **Conhecimento Sympla volta pro scraper:** `scrapers/sympla.py` ganha
  `BILETO_HOST = "bileto.sympla.com.br"` e `id_da_url(url)` (id numérico no
  fim da URL pública; `None` se não tem ou se é Bileto — outro namespace,
  NI-17). O `atualizar.py` para de duplicar a regex `/(\d+)/?$` e a string do
  host em `_descrever` e `_precificar`.

Sem mudança de comportamento nesta parte — é remoção de triplicação.

## 4. Velocidade — janela temporal no precificar (valor 7)

`_precificar` refaz **todos** os eventos futuros a cada rodada, serialmente
com 0,3s de pausa. Correto (preço é volátil), mas o preço de um evento daqui a
4 meses não precisa de atualização diária — quem pergunta ao agente pergunta
de "hoje"/"este fim de semana". É o valor 2 (seleção) aplicado ao valor 7.

- `JANELA_PRECIFICAR_DIAS = 30` (constante em `atualizar.py`): só entram no
  precificar eventos com `start_date` em `[agora, agora + 30 dias]`.
- Flag `--precificar-tudo` restaura o comportamento atual (todos os futuros) —
  útil na primeira carga de uma base recém-recriada.
- **Sem teto silencioso** (mandamento de observabilidade): o log do passo diz
  quantos futuros ficaram **fora** da janela nesta rodada.
- Evento fora da janela mantém o último preço derivado (a Bronze guarda o
  payload de tickets antigo); quando entrar na janela, atualiza.
- Paralelismo (threads + rate limit) fica de fora: medir o ganho da janela
  primeiro, complicar depois se precisar.

## 5. Schema mudou ⇒ base descartável

Coluna `sumido` em `eventos` + tabela `execucoes` ⇒ apagar `data/eventos.db`
e re-raspar (convenção do repo, sem migração). `atualizar._checar_schema`
passa a exigir `sumido`.

## 6. Fora de escopo (deliberado)

- **Versionar payloads na Bronze** (histórico em vez de último-vence): série
  temporal de payload não serve a nenhuma análise do escopo atual e conflita
  com o valor 8. A rastreabilidade que importa vem do run-log (parte 1).
- **Framework de logging/orquestração** (structlog, Airflow etc.): a escala é
  uma rodada manual sob demanda; `print` + `execucoes` cumprem a Constituição.
- **Alerta ativo** (notificação/e-mail): o relatório compara e imprime;
  automação de verdade é a Fase 1 (NI-10), onde o run-log já estará pronto
  para plugar.
- **Migração de schema**: base descartável é decisão documentada da Fase 0.

## 7. Plano de teste

- **`tests/test_observabilidade.py` (novo, base descartável):**
  - execuções: registra duas rodadas com coleta 200 → 80 e confere que a
    comparação detecta queda > 50%;
  - sumido: evento futuro com `raspado_em` antigo → `sumido=1` e some do
    `buscar_eventos`; reaparece no upsert → `sumido=0`; fonte com erro na
    rodada → sumidos da fonte intactos; evento passado nunca marcado;
  - janela do precificar: alvo a 7 dias entra, a 60 dias fica de fora,
    `--precificar-tudo` inclui os dois.
- **Testes existentes seguem passando:** `test_enriquecer.py`,
  `test_bronze.py` (bases descartáveis) e `test_mcp_server.py` (após
  re-raspar a base real).
- **Rodada real** `python src/atualizar.py --sem-shotgun` numa base recriada:
  relatório imprime o bloco novo, `execucoes` ganha a linha, segunda rodada
  compara com a primeira.
