# Spec — Migrar a orquestração para o Dagster (homelab)

> **Status: PROPOSTA (2026-08-14).** Nada implementado. Escrita a pedido do
> autor para decidir se, e como, a orquestração sai do GitHub Actions e vai
> para a instância de Dagster do homelab.
>
> **O quê:** trocar `atualizar.py` disparado por cron do Actions (+ a
> `--rodada-local` manual) por um **grafo de assets no Dagster**, rodando na
> máquina do homelab, que passa a executar a rodada INTEIRA — incluindo o que
> o CI hoje não consegue: Shotgun (Playwright) e a extração de flyer do
> Instagram (`claude -p` na assinatura).
>
> **Por quê** (motivos do autor, na ordem em que ele os deu):
> 1. a estrutura atual é difícil de visualizar e entender no geral;
> 2. observabilidade e controle de qualidade — asset checks;
> 3. controle de gasto de tempo, computação e API;
> 4. acabar com a dependência de "o Mário rodar na mão" para metade das fontes.
>
> **O que a medição desta spec acrescentou como motivo nº 5, e que não estava
> na lista:** a rodada automatizada roda um código DIFERENTE do que o autor
> desenvolve, e a defasagem é invisível — sete rodadas seguidas do cron
> marcadas "success" com a maior fonte do catálogo morta (§1.3).

---

## 1. O que foi medido (2026-08-14)

Números apurados antes de desenhar, contra a instância real e a base de
produção. Não são estimativas.

### 1.1 A instância do homelab

Sondada por GraphQL (`$DAGSTER_URL`, ver `docs/DAGSTER.md`). Está bem mais
pronta do que "instância vazia" sugere:

| | |
|---|---|
| Versão | **1.13.17** (`dagster`, `dagster-postgres` 0.29.17, `dagster-shared`) |
| Run storage / event log / schedule storage | **Postgres** (não SQLite) |
| Scheduler | `DagsterDaemonScheduler` |
| Run coordinator | `QueuedRunCoordinator` |
| Run launcher | **`DefaultRunLauncher`** |
| Artifact storage | `LocalArtifactStorage` em `/opt/dagster/home` |
| Compute logs | não configurado → `LocalComputeLogManager` (o default) — ver §6.6 |
| Daemons | SENSOR, BACKFILL, SCHEDULER, QUEUED_RUN_COORDINATOR, ASSET, FRESHNESS — **todos `healthy: true`, todos `required: true`** |
| Code locations | uma: `definitions.py`, `LOADED`, reload suportado |
| Assets | `hello_homelab` (grupo `default`) |
| Runs já executados | **zero** (`runsOrError` → lista vazia) |

Três consequências que decidem o desenho:

1. **`DefaultRunLauncher` + `QueuedRunCoordinator`**: cada run roda como
   **subprocesso do processo que serve a code location**. Não há container por
   run, não há Docker-in-Docker, não há Kubernetes. Isso é ótimo (simples) e
   caro: esse processo precisa carregar tudo — Python, o repo, Chromium, Node,
   Monid, `claude`. E, no arranjo atual, esse processo é o **webserver ou o
   daemon** (§6.1). Toda a §6 sai daqui.
2. **Storage em Postgres + daemon completo**: schedules, sensores, backfills,
   freshness e asset checks funcionam de verdade, sem nada a instalar. Não é
   um `dagster dev` de brinquedo.
3. **Só `dagster` e `dagster-postgres` estão instalados** na code location.
   Nenhuma dependência do raspador existe lá — nem `psycopg`.

### 1.2 O pipeline hoje

Duração por modo, de `operacao.execucoes` (42 rodadas registradas):

| Modo | Rodadas | Média | Máx. |
|---|---|---|---|
| `cron` (Actions, sem Shotgun, sem visão) | 14 | **737 s** (12 min) | 1003 s |
| `completo` (local, tudo) | 4 | **1486 s** (25 min) | 2124 s |
| `so-derivar` (tratamento a seco) | 16 | **26 s** | 39 s |
| `so-enriquecer` | 6 | 5 s | 8 s |
| `rodada-local` (Shotgun + flyer) | 2 | 149 s | 175 s |

Tempo de coleta por fonte (`operacao.coletas`, agosto):

| Fonte | Média | Observação |
|---|---|---|
| shotgun | **230 s** | Playwright, ~4 páginas |
| ticketandgo | **197 s** | varre ~37 páginas do catálogo nacional |
| zig | 8 s | catálogo nacional, filtro local |
| sympla | 3 s | API de descoberta paginada |
| ingresse | 2 s | catálogo de Brasília é pequeno |

**As cinco fontes rodam em SÉRIE hoje** (`_raspar` é um `for`). A soma é
~440 s; o caminho crítico real seria 230 s. Não é o maior custo da rodada — os
passos "descrever" e "precificar" fazem uma requisição por evento com
`sleep(0.3–0.4)` —, mas é o ganho mais barato de obter (§7.2).

O tratamento inteiro custa **26 s** e é uma transação só. Isso é o que
autoriza a §4.3.

### 1.3 Três achados da medição

**(a) O cron está desligado desde 11/08, e isso é deliberado.** `gh workflow
list` → `raspar  disabled_manually`; a última rodada agendada foi **11/08
06:55**. O autor pediu a pausa para fazer justamente estas correções no
pipeline, e **não está rodando atualizações**: a base está congelada de
propósito. Consequência para esta spec: as datas de `raspado_em` da tabela
abaixo são um retrato de uma base parada, não sintoma de abandono — e é por
isso que a comparação com a rodada anterior (§9) só volta a fazer sentido
depois da primeira rodada nova.

**(b) O Sympla passou sete rodadas seguidas morto, e o Actions disse
"success".** De 05/08 a 11/08, toda coleta do Sympla no cron registrou
`HTTPError: HTTP Error 405: Method Not Allowed` — `coletados = NULL`. O fix
(`bf729b7`, "API de descoberta passou a exigir POST") é de **04/08** e estava
no repositório local; os runs do cron desses dias usaram o SHA **`cdd7938`, de
02/08** (`gh run list --json headSha`). O push só aconteceu **hoje, 14/08**.

> Investiguei a hipótese "o Sympla bloqueia o IP do runner, como o Shotgun".
> **É falsa**: o SHA que rodava no CI era anterior ao fix. O mesmo código, aqui,
> agora, devolve 200 e 270 eventos. A causa é a distância entre onde o código é
> escrito e onde ele é executado — não a rede.

O efeito na base é medível: o Sympla tem **180 eventos futuros** com
`raspado_em` de **07/08** — ele só é coletado quando o autor roda na mão.

| Fonte | Futuros | `raspado_em` mais recente |
|---|---|---|
| sympla | 180 | **2026-08-07T11:51** (7 dias) |
| shotgun | 49 | **2026-08-07T11:56** (7 dias) |
| ticketandgo | 67 | 2026-08-11T06:56 |
| instagram | 23 | 2026-08-11T07:03 |
| ingresse | 3 | 2026-08-11T06:56 |
| zig | 1 | 2026-08-10T07:19 |

**Com o cron LIGADO, 229 dos 323 eventos futuros — 71% — já não eram
atualizados por ele**: o Shotgun (49) por desenho, desde o NI-58, e o Sympla
(180) por um bug que o CI reportava como sucesso. Os dois só andavam quando o
autor rodava `--rodada-local` na mão. A pausa de 11/08 não criou esse buraco;
ela só o deixou visível na mesma tabela.

**(c) A guarda NI-59 fez o trabalho dela.** Com `coletados = NULL` e `erro`
preenchido, `sumido.ultima_coleta_boa` ignorou o Sympla e os 180 eventos
seguiram visíveis no site. O desenho aguentou; o que faltou foi **alguém ser
avisado**. É exatamente o buraco que asset checks fecham.

---

## 2. O que a migração precisa entregar

Critérios de aceitação, para não confundir "migrou" com "melhorou":

1. **Uma rodada diária, automática, com TODAS as fontes** — incluindo Shotgun e
   a extração de flyer. A `--rodada-local` deixa de ser obrigatória.
2. **Cada fonte visível como uma coisa**: quando o Sympla morre, o Sympla fica
   vermelho — não a rodada inteira "success".
3. **Alarme que chega até o autor sem ele abrir a UI.** Um painel que ninguém
   olha não é observabilidade (é o mesmo argumento do relatório de feedback já
   embutido no relatório da rodada).
4. **Tempo e custo por passo registrados como número**, série histórica, não
   texto em log: segundos por fonte, requisições, posts extraídos, dólares do
   Monid.
5. **O `atualizar.py` continua funcionando** sem Dagster nenhum. É o rollback e
   é o modo de desenvolvimento.
6. **Nenhuma regra de negócio nova, nenhuma alteração de comportamento** na
   fatia de migração. Quem muda comportamento é fatia própria, depois.

> **Janela de indisponibilidade: autorizada, e provavelmente desnecessária.** O
> site está em produção e é público, mas tem pouquíssimo uso ativo agora, e o
> autor liberou tirá-lo do ar durante a migração (14/08). Não deve ser preciso:
> o Dagster escreve na mesma base pelos mesmos passos, e a §4.3 preserva a
> transação única justamente para o site continuar servindo durante a
> reconstrução. A autorização vale como **rede de segurança** para o único
> cenário que a exigiria — algo destrutivo em `tratado` que precise rodar sem
> leitor concorrente. Se for usada, o modo é pausar o deploy da Vercel, não
> mexer na base.

---

## 3. Decisões

Marcadas ✅ as que o autor decidiu em 14/08; as demais são propostas desta spec.

| | Decisão | Por quê |
|---|---|---|
| **D1** ✅ | **Bind mount de um clone git**, não imagem por CI para o código | Iteração sem build/registry. Consequência aceita e endereçada: as DEPS entram por imagem (§6.1) e o SHA vira metadata do run (§6.2) |
| **D2** ✅ | **Escopo total**: Shotgun e Instagram (Monid + visão) vão para o servidor | É o motivo nº 4. Sem isso a migração troca um cron por outro |
| **D3** ✅ | **O Actions vira fallback desligado**, com `workflow_dispatch` e sem `schedule` | O homelab é ponto único de falha (energia, internet, Tailscale). Um clique restaura a cadência |
| **D4** ✅ | **Coleta com assets finos, tratamento como asset grosso** | O ciclo é uma transação só — fatiá-lo em assets mentiria sobre a garantia (§4.3) |
| **D5** ✅ | **`src/` NUNCA importa `dagster`** | O Dagster é um CHAMADOR, como o `atualizar.py`. É o que mantém o rollback real e o teste local barato (§5.1) |
| **D6** ✅ | **Falha de fonte é DADO, não crash**: o asset materializa com `{"erro": ...}` e o *check* fica vermelho | É a regra que já existe ("uma fonte quebrada não esconde as outras"). Se o asset falhasse, o run pararia e o tratamento não rodaria — pior que hoje |
| **D7** ✅ | **Sem partições** na v1 | O `cru` não é particionado por data e a fonte só entrega o presente: não existe backfill de "o catálogo de terça". Partição sem re-materialização possível é decoração |
| **D8** ✅ | **Assets de coleta retornam um `dict` pequeno**, entregue ao asset final pelo IO manager padrão | É como o `operacao.execucoes` continua sendo escrito no formato de hoje, sem inventar canal lateral (§5.3). **Depende da §6.0**: sem code location dedicada e volume compartilhado, o output escrito por um container não existe para o outro |
| **D9** ✅ | **Um job só na v1** (`rodada_diaria`), com sub-jobs por seleção de assets | `--so-derivar` vira "materializar o grupo `tratamento`". Menos peças |
| **D10** ✅ | **Schedule com `execution_timezone="America/Sao_Paulo"`** | O cron do Actions é UTC e *best effort*; aqui é pontual e legível ("03:00", não "0 6 * * *" com um comentário explicando) |
| **D11** ✅ | **O relatório de saúde continua existindo** | É o que o autor lê. Vira stdout do asset final + metadata; não é substituído pela UI, é duplicado nela |
| **D12** ✅ | **O módulo Dagster NÃO pode se chamar `dagster`** | `src/pipeline/dagster/` sombrearia o pacote real e quebraria o import de dentro do próprio código. Nomes: `definitions.py`, `checks.py` |

---

## 4. O grafo de assets

### 4.1 O mapa

Chaves com prefixo de camada — a AssetKey espelha o schema onde o dado cai, e o
grafo passa a ser lido do mesmo jeito que a arquitetura (`cru/…`, `tratado/…`,
`operacao/…`).

```
grupo: coleta                                grupo: tratamento

cru/sympla ──────┐
cru/ingresse ────┼──→ cru/detalhes ──→ cru/tickets ──┐
cru/zig ─────────┤                                    │
cru/ticketandgo ─┘                                    │
                                                      ├──→ tratado/eventos  ┐
cru/shotgun ──────────────────────────────────────────┤    tratado/filmes   ├─ 1 compute,
                                                      │    tratado/sessoes  ┘  1 transação
cru/cinema ───────────────────────────────────────────┤
                                                      │            │
cru/instagram ──→ cru/extracao_flyer ──→ operacao/midias           ↓
                                                      │    cru/tmdb ──→ operacao/posters
                                                      │            │
                                                      └────────────┴──→ operacao/execucao
                                                                            (relatório + linha
                                                                             em execucoes)
```

`cru/tmdb` e `operacao/posters` ficam DEPOIS do tratamento de propósito: a
lista do que está em cartaz É a tabela `tratado.filmes` — não há como montá-la
antes. Hoje o `atualizar.py` roda o ciclo de novo se eles trouxeram algo; no
Dagster isso é uma re-materialização do grupo `tratamento`, e é o único ponto
do grafo em que a dependência é cíclica no tempo. Ver §4.5.

### 4.2 Asset por asset

| Asset | Chama | Escreve em | Custo típico |
|---|---|---|---|
| `cru/sympla` | `passos.coletar("sympla")` | `cru.sympla`, `operacao.coletas` | 3 s |
| `cru/ingresse` | idem | `cru.ingresse`, `operacao.coletas` | 2 s |
| `cru/zig` | idem | `cru.zig`, `operacao.coletas` | 8 s |
| `cru/ticketandgo` | idem (recebe `locais_df` de `curado.locais`) | `cru.ticketandgo`, `operacao.coletas` | 197 s |
| `cru/shotgun` | idem (Playwright) | `cru.shotgun`, `operacao.coletas` | 230 s |
| `cru/detalhes` | `passos.descrever` | `cru.<fonte>` origem `detalhe` | 1 req/evento novo |
| `cru/tickets` | `passos.precificar` | `cru.<fonte>` origem `tickets` | 1 req/evento na janela de 30 d |
| `cru/cinema` | `passos.coletar_cinema` | `cru.cinema` | 8 cinemas × 8 dias |
| `cru/instagram` | `passos.coletar_instagram` | `cru.instagram` | ~$0,006/perfil |
| `cru/extracao_flyer` | `passos.extrair_flyers` | `cru.instagram` origem `extracao` | ~60 s/post, assinatura |
| `operacao/midias` | `passos.subir_midias_instagram` | `operacao.midias`, Blob | incremental |
| `tratado/eventos` + `tratado/filmes` + `tratado/sessoes` | `ciclo.executar` | `tratado.*` (uma transação) | 26 s |
| `cru/tmdb` | `passos.enriquecer_cinema` | `cru.tmdb` | 1 req/filme novo |
| `operacao/posters` | `passos.copiar_posters` | `operacao.midias`, Blob | incremental |
| `cru/podado` | `gravar.podar_historico` | `cru.*` (poda > 90 dias) | segundos |
| `operacao/execucao` | `passos.relatorio` + `execucoes.registrar_execucao` | `operacao.execucoes` | segundos |

### 4.3 Por que o tratamento é UM compute com três assets

`tratamento/ciclo.py` roda oito passos e comita **uma vez**, com `DELETE` e não
`TRUNCATE`, porque `public` é view sobre `tratado` e o site consulta enquanto
isso acontece. Quebrar isso em oito assets do Dagster significaria oito commits
— e uma janela em que o site serve "nenhum evento encontrado". Não é aceitável,
e a spec do medalhão §8.1 já pagou para aprender.

A saída é `@multi_asset`: **um compute, três assets materializados**. O grafo
ganha granularidade visual (eventos, filmes e sessões aparecem separados, com
metadata e checks próprios) sem que a transação seja tocada.

```python
@dg.multi_asset(
    specs=[dg.AssetSpec(["tratado", "eventos"], deps=[...]),
           dg.AssetSpec(["tratado", "filmes"], deps=[...]),
           dg.AssetSpec(["tratado", "sessoes"], deps=[...])],
    group_name="tratamento",
)
def tratado(context, **coletas):
    con = conexao.conectar()
    try:
        saida = ciclo.executar(con)          # a transação continua sendo dele
    finally:
        con.close()
    yield dg.MaterializeResult(["tratado", "eventos"], metadata={...})
    yield dg.MaterializeResult(["tratado", "filmes"], metadata={...})
    yield dg.MaterializeResult(["tratado", "sessoes"], metadata={...})
```

**Regra que precisa ficar escrita:** nenhum asset novo pode abrir sua própria
transação sobre `tratado`. Quem escreve na prata é `ciclo.executar`, e ponto —
é a mesma fronteira do CLAUDE.md, agora com um jeito novo de ser violada.

### 4.4 Por que os assets não trafegam dados

O dado real anda pelo Neon, não pelo Dagster. As dependências do grafo são
**ordenação e linhagem**, não transporte. Por isso os assets devolvem apenas o
dicionário de resultado (contagens, erros, duração) — algumas centenas de bytes
que o IO manager padrão guarda em `/opt/dagster/home`.

Consequência a não esquecer: **re-materializar um asset de coleta não
"restaura" nada** — ele vai à fonte de novo, e a fonte só sabe do presente. O
botão "Materialize" da UI é um gatilho, nunca um retrocesso.

**Plano B do D8, se o volume compartilhado incomodar.** O recibo de cada coleta
já está na base: `execucoes.registrar_coleta` grava fonte, início, fim,
`coletados`, `total_site` e `erro` em `operacao.coletas` antes de o asset
retornar. O asset final poderia, então, **remontar o dicionário lendo a própria
base**, e aí nenhum output precisaria atravessar containers — o IO manager
viraria detalhe irrelevante. Não é o caminho preferido porque exige reconstruir
em SQL um formato que hoje é passado de mão em mão em memória, e é justamente
esse formato que o alerta de queda de 50% consome. Fica registrado como saída
barata caso a §6.0 se mostre frágil na prática.

### 4.5 O laço do TMDB

Hoje: tratamento → TMDB/pôster → tratamento de novo (se trouxeram algo). Num
DAG isso não se expressa. Três saídas, em ordem de preferência:

1. **`cru/tmdb` e `operacao/posters` downstream do tratamento; o segundo ciclo
   é o da rodada do dia seguinte.** O filme novo fica sem sinopse por ≤24 h.
   Simples, honesto, e o custo é invisível para quem usa (a estreia entra na
   grade com nota na quinta seguinte à quinta em que apareceu — hoje entra no
   mesmo dia).
2. Um segundo asset `tratado/refresh` que só roda se os dois trouxeram algo.
   Duplica o nó no grafo — feio, mas preserva o comportamento exato.
3. Manter o `ciclo.executar` duplo dentro do próprio asset final. Esconde no
   compute o que o grafo deveria mostrar.

**Recomendo (2)** para a migração — a regra é "nenhuma mudança de
comportamento" (§2.6) — e (1) como simplificação a discutir depois, medindo
quantos filmes por semana são afetados de fato.

---

## 5. O que muda no código

### 5.1 A regra: `src/` não importa `dagster`

O Dagster entra como mais um chamador dos mesmos passos, na mesma posição que o
`atualizar.py` ocupa hoje. Nenhum módulo de `coleta/`, `tratamento/`, `base/`
ou `servico/` ganha `import dagster`.

Três razões, e a terceira é a que importa:

1. **Rollback**: se o homelab não vingar, apaga-se `definitions.py` e o
   `atualizar.py` continua rodando.
2. **Teste**: os testes de fumaça (`tests/*.py`) continuam sendo scripts
   executáveis sem framework — não precisam de instância Dagster nenhuma.
3. **A lição do NI-55**: a fronteira que não é física é convenção verbal, e
   convenção verbal não se sustenta. Um `@asset` decorando `tratamento/comum.py`
   seria o começo da orquestração morando dentro da regra de negócio outra vez.

### 5.2 `src/pipeline/passos.py` — o refactor de verdade

É a fatia com risco real, e é toda de **movimentação, sem alteração de lógica**.
Hoje a orquestração e os passos vivem juntos em `atualizar.py` (906 linhas), com
os passos como funções privadas `_descrever`, `_precificar`… Elas precisam
virar API pública para o Dagster chamar sem duplicar código.

| Hoje (`atualizar.py`) | Vira (`passos.py`) | Mudança |
|---|---|---|
| `_raspar(incluir_shotgun, apenas, locais_df)` — loop de 5 fontes | **`coletar(nome, locais_df=None)` — UMA fonte** | A única quebra de forma: o loop sai para quem chama. É o que permite um asset por fonte |
| `_descrever(con, erros)` | `descrever(con, erros)` | renome |
| `_precificar(con, erros, tudo)` | `precificar(...)` | renome |
| `_fila`, `_sumiu` | idem, privadas do módulo | — |
| `_raspar_cinema(erros)` | `coletar_cinema(erros)` | renome |
| `_raspar_instagram(erros, extrair)` | **`coletar_instagram(erros)` + `extrair_flyers(erros)`** | Separa a coleta da visão: hoje é uma função com um `if extrair`, e no grafo são dois assets com custos, pools e falhas diferentes |
| `_enriquecer_cinema`, `_copiar_posters`, `_subir_midias_instagram` | idem, públicas | renome |
| `_relatorio(...)`, `_coleta_anterior`, `_checar_schema` | idem, públicas | renome |
| `main()` | fica em `atualizar.py` | O CLI continua sendo o CLI: lê `sys.argv`, chama os passos na ordem, imprime |

**Feito em 14/08.** Três coisas que a execução acrescentou ao plano acima:

- A separação do Instagram deixou um terceiro pedaço: a **fila** de extração
  (`_fila_extracao`) é lida pelos dois lados, porque a rodada que NÃO extrai
  ainda precisa dizer quantos posts ficaram esperando. Virou
  `pendentes_extracao()`, e é o que o `atualizar.py` chama no modo do cron. Sem
  ela, o pendente ficaria invisível justamente na rodada que não o processa.
- O `atualizar.py` ficou com duas funções de orquestração, não só `main()`:
  `_raspar` (o loop das cinco fontes, que agora é três linhas sobre
  `passos.coletar`) e `_instagram` (coleta + visão, ou coleta + contagem). São
  decisões de CLI — o Dagster vai tomar as suas próprias, com um asset por passo.
- O patch de `FORCAR_IPV4` no `socket.getaddrinfo` mudou de arquivo junto com os
  passos, e **mora em `passos.py` de propósito**: é decisão de pipeline. Quem
  importa `base/conexao.py` para só ler a base (site, MCP, testes) não deve
  ganhar um patch global no `socket` de brinde.

**Como se prova que o refactor não mudou nada** (§13): uma rodada `--so-derivar`
antes e depois com diff nas contagens, a suíte de fumaça inteira, e uma rodada
`completo` comparada com a rodada anterior em `operacao.execucoes`. As três
foram feitas; o resultado de cada uma está na fatia 1, na §12.

### 5.3 `src/pipeline/definitions.py` — esboço

Não é o código final; é o contrato que a fatia 2 implementa.

```python
import dagster as dg
from base import conexao
from pipeline import execucoes, passos
from tratamento import ciclo, curadoria

RETRY = dg.RetryPolicy(max_retries=2, delay=30, backoff=dg.Backoff.EXPONENTIAL)


def _asset_de_fonte(nome, pool="rede", **kw):
    @dg.asset(key=["cru", nome], group_name="coleta", pool=pool,
              retry_policy=RETRY, **kw)
    def _asset(context):
        con = conexao.conectar()
        try:
            locais = curadoria.nomes_df(con)
        finally:
            con.close()
        res = passos.coletar(nome, locais_df=locais)      # já registra a coleta
        # D6: fonte quebrada NÃO derruba o run — vira metadata e check vermelho
        return dg.MaterializeResult(
            value=res,
            metadata={"coletados": res.get("coletados"),
                      "total_site": res.get("total_site"),
                      "erro": res.get("erro") or "",
                      "duracao_s": res.get("duracao_s")})
    return _asset


FONTES = [_asset_de_fonte(n) for n in
          ("sympla", "ingresse", "zig", "ticketandgo", "shotgun")]

rodada = dg.define_asset_job("rodada_diaria", selection="*")

defs = dg.Definitions(
    assets=[*FONTES, ...],
    asset_checks=[...],                      # §8
    jobs=[rodada],
    schedules=[dg.ScheduleDefinition(
        job=rodada, cron_schedule="0 3 * * *",
        execution_timezone="America/Sao_Paulo")],
)
```

Pontos do esboço que são decisão, não estilo:

- **`value=res` no `MaterializeResult`**: é o D8 — o asset final recebe os
  dicionários e escreve `operacao.execucoes` no formato exato de hoje. O
  `_coleta_anterior` do relatório depende desse formato (`fontes[nome].coletados`);
  se ele mudar, o alerta de queda de 50% para de funcionar em silêncio.
- **`pool="rede"`**: §7.2.
- **`retry_policy` na coleta**: re-tentar é seguro porque o `cru` é append-only
  com dedupe por hash — payload igual não vira linha nova. Não vale para
  `cru/extracao_flyer`, que gasta cota da assinatura por tentativa.
- **Conexões curtas**: cada asset abre e fecha a sua, como hoje. Conexão parada
  durante minutos de rede é derrubada em silêncio pelo Neon (visto no Zig).

### 5.4 Arquivos

```
src/pipeline/
  atualizar.py     # CLI — continua, encolhe para ~200 linhas (orquestração + main)
                   #   (feito: 906 -> 238 linhas)
  passos.py        # NOVO — os passos, chamáveis por qualquer orquestrador
                   #   (feito: 769 linhas)
  definitions.py   # NOVO — assets, jobs, schedules (só ele importa dagster)
                   #   (fatia 2: um asset de diagnóstico; o grafo vem na 3)
  checks.py        # NOVO — asset checks (leem a base, a seco)
  execucoes.py     # inalterado
```

`docs/DAGSTER.md` passa de "acesso verificado" a "como a orquestração roda",
e o `CLAUDE.md` ganha a seção correspondente. `linhagem.py` lê o próprio código
para gerar `docs/linhagem/` — **conferir se o refactor de `atualizar.py` quebra
o gerador** (ele conhece a estrutura dos passos).

---

## 6. O ambiente do servidor

O servidor inteiro é versionado em **`github.com/oextraordimario/homelab`**,
lido em 14/08. Três stacks, um `docker-compose.yml` cada: `dagster/`, `n8n/` e
`metabase/`. O que resta de incógnita está na §15.

### 6.0 O arranjo atual, e por que ele precisa de um serviço novo

Hoje são **três serviços**: `dagster_webserver`, `dagster_daemon` (ambos
`build: .`, a mesma imagem) e `dagster_pg` (postgres:16-alpine, dados em
`./pg-data`). O `dagster.yaml` configura **só o storage**; todo o resto é
default. Os dois primeiros montam `./pipelines:/opt/dagster/pipelines` e o
webserver aponta para `/opt/dagster/home/workspace.yaml`.

O `Dockerfile` (7 linhas) explica o resto:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir dagster dagster-webserver dagster-postgres pandas requests
ENV DAGSTER_HOME=/opt/dagster/home
RUN mkdir -p $DAGSTER_HOME
COPY dagster.yaml workspace.yaml $DAGSTER_HOME/
WORKDIR $DAGSTER_HOME
```

E o `workspace.yaml` confirma o modo de carregamento:

```yaml
load_from:
  - python_file:
      relative_path: /opt/dagster/pipelines/definitions.py
```

`python_file` = carregamento **in-process**, exatamente o diagnóstico abaixo. E
`dagster.yaml`/`workspace.yaml` entram por **`COPY`**: mudar pool, concorrência
ou code location exige `docker compose build`. Duas consequências novas, que
não estavam na spec antes de o repositório ser lido, entram na fatia 0.

**Não existe serviço de code location.** Webserver e daemon carregam o código
eles mesmos. Combinado com o `DefaultRunLauncher`, isso produz três problemas
que só aparecem quando a carga deixa de ser um `hello_homelab`:

1. **O run nasce no container de quem o lançou.** Schedule → daemon. Botão
   "Materialize" na UI → webserver. Ou seja, o **webserver passaria a rodar
   Chromium e a raspar o Sympla** enquanto serve a interface. Um pico de
   memória na raspagem derruba a UI junto.
2. **Os dois containers têm filesystems separados**, e `/opt/dagster/home`
   **não tem volume**. O IO manager padrão grava em `$DAGSTER_HOME/storage`:
   um output escrito por um run do daemon simplesmente não existe para um run
   lançado pelo webserver. É o D8 quebrando de um jeito difícil de diagnosticar
   ("FileNotFoundError" num asset que materializou com sucesso ontem).
3. **Tudo em `/opt/dagster/home` é efêmero.** Compute logs e artefatos morrem no
   próximo `docker compose up --build`. Só o Postgres (`./pg-data`) e o código
   (`./pipelines`) sobrevivem.

**O que a spec propõe:** um quarto serviço, `raspador_code`, servindo a code
location por gRPC, com a imagem pesada; webserver e daemon continuam magros e
passam a ser só interface e agendador. Ganhos, além de resolver os três pontos
acima: `docker compose restart raspador_code` recarrega o código **sem derrubar
a UI**, e as dependências do raspador não contaminam a instância inteira do
homelab (que é para ter outros usos).

Junto vêm três mudanças pequenas e necessárias no que já existe:

- **um `/opt/dagster/home` compartilhado pelos TRÊS serviços**. A UI lê compute
  log do disco *dela* — sem disco compartilhado, o log do run some da interface,
  mesmo existindo no container que o produziu;
- **`workspace.yaml` e `dagster.yaml` vindo de fora da imagem**, senão declarar
  a code location nova, ou mexer em pool, exige rebuild;
- **pinar a versão do Dagster** no `Dockerfile` — hoje é `pip install dagster`
  sem versão (ver o risco na §6.1).

⚠️ **A armadilha do `DAGSTER_HOME`, corrigida em execução (14/08).** O plano
original era volume nomeado + os dois YAMLs montados por cima como bind mount de
arquivo. A razão continua válida — volume nomeado montado sobre diretório que
tem conteúdo na imagem copia esse conteúdo **uma única vez**, na criação, e a
partir daí congela a config sem erro nenhum na tela. Mas a saída proposta tinha
o mesmo defeito por outro mecanismo, e ele só apareceu ao testar:

> **Bind mount de ARQUIVO é preso ao inode.** `sed -i` e `git pull` não editam o
> arquivo no lugar: escrevem um temporário e renomeiam por cima. Inode novo, e o
> container segue lendo o antigo. **Medido:** host com `max_concurrent_runs: 2`,
> `docker exec ... grep` dentro do container mostrando `1`, e o GraphQL
> (`instance { runQueueConfig { maxConcurrentRuns } }`) confirmando `1`. Como
> toda mudança de configuração chega por `git pull`, isso significaria config do
> repositório ignorada em silêncio — exatamente o que a armadilha original
> descrevia.

A saída é **bind mount de DIRETÓRIO**: `dagster/home/` no repo `homelab` vira o
`DAGSTER_HOME` inteiro, com os dois YAMLs versionados lá dentro e
`storage/`/`compute_logs/` gitignorados. Diretório não sofre do problema de
inode (o container enxerga a substituição na hora), é o mesmo disco para os três
serviços, é inspecionável sem `docker volume inspect` e não congela nada:

```yaml
    volumes:
      - ./home:/opt/dagster/home
```

```yaml
  raspador_code:                      # SERVIÇO NOVO
    build: ./raspador-image           # Python+Node+Chromium+CLIs (§6.1)
    restart: unless-stopped
    command: dagster api grpc -h 0.0.0.0 -p 4000
             -f /opt/raspador/src/pipeline/definitions.py
    working_dir: /opt/raspador
    environment:
      PYTHONPATH: /opt/raspador/src   # sem isto, `from base import ...` falha
      DAGSTER_HOME: /opt/dagster/home
      DAGSTER_PG_PASSWORD: ${DAGSTER_PG_PASSWORD}
      TZ: America/Sao_Paulo
    env_file: .env                           # EVENTOS_DB_URL, TMDB, BLOB (§6.3)
    volumes:
      - /srv/raspador_eventos:/opt/raspador  # o clone git (D1)
      - /srv/claude-home:/root/.claude       # credencial da assinatura (§6.4)
      - ./home:/opt/dagster/home             # o mesmo disco do webserver/daemon
```

```yaml
# workspace.yaml
load_from:
  - grpc_server:
      host: raspador_code
      port: 4000
      location_name: raspador
```

O `TZ: America/Sao_Paulo` que os dois serviços já têm precisa valer no novo
também — é o que faz o horário do schedule (§7.1) e o dia local de Brasília
baterem com o resto do projeto.

⚠️ **`PYTHONPATH=/opt/raspador/src` não é detalhe.** Os entrypoints do projeto
funcionam porque `sys.path[0]` vira `src/` ao rodar `python src/pipeline/x.py`.
Carregado por `-f`, o Dagster não faz isso — sem `PYTHONPATH`, a code location
falha no `from base import conexao`, e o erro aparece na UI como "location
failed to load", não como um ImportError óbvio.

### 6.1 O que a imagem do `raspador_code` precisa

Com `DefaultRunLauncher`, é esse container que executa tudo:

| Requisito | Por causa de | Observação |
|---|---|---|
| Python 3.12+ | `pyproject.toml` | hoje o autor roda 3.13 |
| `requirements.txt` | tudo | `psycopg[binary]`, `playwright`, `pyyaml`, `pandas` |
| `dagster` 1.13.17 | code location | **mesma versão do webserver/daemon** — versão diferente entre daemon e code location é fonte clássica de erro obscuro |
| **Chromium** | Shotgun | `python -m playwright install --with-deps chromium`, ~400 MB |
| **Node 22 + `@monid-ai/cli`** | Instagram | chave via `monid keys add` (fica no config do monid) |
| **`claude` CLI logado** | extração de flyer | §6.4 — o item mais arriscado |
| Rede de saída | 7 domínios + Neon + Blob + api.anthropic/claude.ai | homelab em IP residencial: é o que faz o Shotgun funcionar |
| Escrita em `midias/instagram/` | flyers baixados | dentro do bind mount ou volume próprio |

**Nada disso cabe na imagem atual** (`build: .`, que só carrega o Dagster). O
`Dockerfile` do `raspador_code` é próprio — Node + Chromium +
`dagster==1.13.17` + `requirements.txt`. Ele muda raramente (só quando entra
dependência nova); o **código** entra por bind mount (D1). Na prática é o
arranjo híbrido: imagem para o ambiente, mount para o repo.

**Derivar da imagem atual ou não.** A base dela é `python:3.12-slim`, que serve
— o projeto pede 3.12+ e nada usa recurso de 3.13. Mas a imagem do raspador
precisa de Chromium com as bibliotecas de sistema dele, e a rota mais curta
para isso é `mcr.microsoft.com/playwright/python:v1.5x-noble`, que já traz
navegador e dependências resolvidas; a alternativa é `python:3.12-slim` +
`playwright install --with-deps chromium`, que funciona e faz `apt` puxar ~120
pacotes. Escolher na fatia 2, medindo o tamanho. O que **não** deve acontecer é
o `raspador_code` herdar do Dockerfile atual: eles têm ciclos de vida
diferentes, e uma dependência do raspador quebrando o rebuild derrubaria a UI
do homelab junto.

**Escolhido em 17/08: `python:3.12-slim` + `playwright install --with-deps
chromium`.** O que decidiu não foi o tamanho, foi o pin: o `requirements.txt`
declara piso (`playwright>=1.57`), então a versão da lib é resolvida no build —
e a imagem `mcr.microsoft.com/playwright/python:v1.5x` traz um navegador
casado com UMA versão da lib. As duas ficariam presas uma à outra, e o dia em
que o pip resolvesse 1.60 sobre a tag 1.57 o sintoma seria "Executable doesn't
exist" no meio de uma rodada. Instalando o navegador pelo próprio playwright
recém-instalado, quem escolhe o navegador é sempre a lib que vai usá-lo.

⚠️ **O `pip install dagster` sem versão é uma bomba-relógio de fuso longo.**
Hoje ele resolveu 1.13.17 nos dois serviços — como eles compartilham a imagem,
sempre batem entre si. Com uma segunda imagem entra a possibilidade de
divergirem: um rebuild do webserver daqui a três meses traz 1.14 ou 1.15, o
`raspador_code` continua em 1.13.17, e o protocolo gRPC entre eles é
versionado. O sintoma é code location que "falha ao carregar" com erro de
serialização, sem relação aparente com o que se estava fazendo. **Pinar a mesma
versão exata nos dois Dockerfiles, e subi-la nos dois de uma vez** — a fatia 0
inclui isso, e é a mudança mais barata desta spec inteira.

### 6.2 Dois repositórios, e o SHA como metadata

**Quem é dono de quê.** A migração cria uma fronteira entre dois repositórios,
e ela precisa ficar escrita antes de alguém decidir no impulso:

| Fica em `homelab` | Fica em `raspador_eventos` |
|---|---|
| `docker-compose.yml`, `Dockerfile` do Dagster, `dagster.yaml`, `workspace.yaml` | `src/pipeline/definitions.py`, `checks.py`, `passos.py` |
| ~~o `Dockerfile` do `raspador_code`~~ → **mudou na fatia 2, ver abaixo** | `docker/raspador_code.Dockerfile` + `.dockerignore` |
| `.env` com `DAGSTER_PG_PASSWORD` (gitignorado) | tudo que sabe o que é um evento |

⚠️ **O Dockerfile do `raspador_code` mudou de repositório na execução (17/08).**
A linha acima dizia que ele é "infraestrutura da máquina" e ficaria no
`homelab`. Ao escrevê-lo, o critério do D5 apontou para o outro lado: a imagem
existe para satisfazer o `requirements.txt`, e `COPY requirements.txt` exige o
arquivo dentro do contexto de build. Com o Dockerfile no `homelab` sobravam
três saídas, todas piores — **duplicar** o requirements lá (defasagem em
silêncio, a classe de erro que esta spec inteira ataca), **instalar em runtime**
a cada `restart` (o container passa a depender do PyPI para subir, e o que está
instalado deixa de ser propriedade da imagem) ou **`additional_contexts`** do
Compose (sintaxe pouco conhecida, e exige versão recente). Dependência nova
nasce junto de código novo e os dois têm que viajar no mesmo commit, que é
exatamente o argumento usado abaixo para o `definitions.py`.

Quem **declara** o serviço continua sendo o `docker-compose.yml` do `homelab`;
o que ele ganhou foi `context: /srv/raspador_eventos` +
`dockerfile: docker/raspador_code.Dockerfile`. E o contexto é enxuto por
`.dockerignore` (`*` seguido de `!requirements.txt`): o código chega por bind
mount, então nada além do requirements precisa viajar para o daemon do Docker.

O critério é o mesmo do D5: **o `definitions.py` do raspador mora no repo do
raspador**, porque asset novo quase sempre nasce junto de passo novo, e os dois
precisam ser um commit só. Separá-los recriaria o achado §1.3(b) num lugar
novo — a defasagem passaria a ser entre dois repositórios em vez de entre
máquinas.

Isso é uma diferença deliberada em relação ao `hello_homelab`, que mora em
`homelab/dagster/pipelines/`. A pasta continua existindo para os pipelines que
forem do servidor; o raspador entra por outra porta (o gRPC da §6.0), e é por
isso que ele **não** usa `./pipelines`. Vale registrar no `README` do homelab,
senão daqui a seis meses ninguém lembra por que há dois mecanismos.

Nota de higiene, à parte: `dagster/pipelines/__pycache__/` está versionado no
homelab. Uma linha no `.gitignore` resolve.

**O SHA.** O achado §1.3(b) é a razão do resto desta subseção. Bind mount tem exatamente
a mesma doença do "roda do main remoto": **o que executa pode não ser o que
você escreveu**, e nada avisa.

Três medidas, e nenhuma é opcional:

1. **Um asset (ou o passo inicial do job) faz `git pull --ff-only`** no clone,
   antes de qualquer coleta, e reporta o SHA resultante.
2. **O SHA vai para a metadata do run** (`context.log` + metadata do asset
   `operacao/execucao`), e para `operacao.execucoes` como campo novo. Ficaria
   registrado, por rodada, qual código produziu aquele dado — coisa que hoje
   não existe em lugar nenhum.
3. **Um asset check compara o SHA local com `origin/main`** e fica amarelo se o
   clone estiver atrás. É a versão automatizada do que só se descobriu hoje
   olhando `gh run list` à mão.

Reload da code location depois do pull: o Dagster carrega o código uma vez, no
servidor gRPC. `git pull` num run **não** recarrega as definições — só muda o
código que o *próximo* run importa se o processo for reiniciado. Para
definições (assets novos, mudança de schedule) é preciso `Reload` na UI ou
reiniciar o serviço; para o **corpo** dos passos, como cada run é um
subprocesso novo, o código novo já vale. Registrar isso na doc, porque é
contraintuitivo e vai morder.

### 6.3 Segredos

`EVENTOS_DB_URL`, `TMDB_API_KEY`, `BLOB_READ_WRITE_TOKEN` saem dos secrets do
GitHub e passam a viver num `env_file` do compose no servidor (a chave do Monid
continua no config do próprio monid; a do `claude`, na credencial da
assinatura).

**Não usar o launchpad do Dagster para segredo**: config de run fica gravada no
event log em Postgres e visível na UI — e a UI não tem autenticação (§10).

Ponto de atenção do Neon: a memória `neon-ipv6-lento-local` registra IPv6
quebrado na rede do autor, resolvido com `FORCAR_IPV4=1` + `hostaddr` +
keepalives. O servidor está **na mesma rede** que o notebook (confirmado na
§15), então a expectativa é que precise do mesmo tratamento: entrar já com
`FORCAR_IPV4=1` no `env_file` e confirmar na fatia 2, quando o primeiro asset
consultar a base. Sintoma se faltar: conexão que demora dezenas de segundos ou
morre em silêncio no meio de um passo longo — não um erro limpo.

**Medido na máquina do autor em 17/08, antes de o servidor entrar:** o asset de
diagnóstico abre a conexão com o Neon em **0,20 s com o patch e 0,21 s sem** —
ou seja, hoje, aqui, o Neon já não sofre. Duas consequências para a fatia 2:
(a) medir só a conexão com a base **não decide nada** sobre a variável, porque
o custo do IPv6 quebrado aparecia sobretudo nas requisições HTTP das fontes
(BFF do Sympla) — a medição no servidor precisa incluir uma delas; (b) o
`.env` local não define `FORCAR_IPV4`, o que significa que a rodada `completo`
de ontem rodou sem o patch e mesmo assim foi normal. A variável continua no
`env_file` do servidor por precaução (é opt-in e barata), mas quem decide se
ela fica é a medição de uma requisição HTTP lá, não a da base.

**Medido no servidor em 17/08, com o container da fatia 2 de pé**
(`src/ferramentas/diag_rede.py`, dois subprocessos, um com a variável e outro
sem):

| | DNS (v4/v6) | Neon | HTTP (Sympla) |
|---|---|---|---|
| sem `FORCAR_IPV4` | 9 / 9 | 0,26 s | 0,19 s |
| com `FORCAR_IPV4` | 9 / 0 | 0,19 s | 0,13 s |

**O IPv6 do servidor funciona** — nada trava, e a diferença é de centésimos,
não as dezenas de segundos que a memória `neon-ipv6-lento-local` descreve. Ou
seja: aquela rede é a do notebook, não a do servidor.

Duas coisas que só a execução mostrou:

1. **A primeira leitura mentiu**, e mentiu no sentido de confirmar a hipótese:
   0,73 s sem o patch contra 0,25 s com. Era aquecimento (cache de DNS, sessão
   TLS) — e como o script mede sempre o lado "sem" primeiro, a conta caía
   sempre no mesmo lado. Repetir foi o que desmentiu. O `diag_rede.py` passou a
   fazer uma passada de aquecimento descartada, senão ele recomenda ligar a
   variável em rede que não precisa dela.
2. **Decisão: a variável FICA**, agora declarada como cinto de segurança e não
   como remédio. A assimetria é o argumento: manter custa zero (é um filtro na
   resolução, e todo host do projeto tem A record) e protege de um modo de
   falha caro; tirar não ganha nada. O que não pode é ela virar folclore — daí
   a tabela acima e a ferramenta versionada para remedir quando o hospedeiro
   mudar de novo.

### 6.4 O `claude` CLI na assinatura — o item mais arriscado

`instagram.extrair` chama `claude -p --model sonnet --output-format json
--allowedTools Read`, **na assinatura** (decisão do PRD §7), com
`ANTHROPIC_API_KEY` removida do env do subprocesso de propósito. É o que impede
o CI de fazer isso hoje, e é o que precisa passar a funcionar no servidor.

O que a migração exige:

- Autenticar **uma vez** no servidor (login interativo, ou token de longa
  duração gerado no host), e montar o diretório de credenciais no container
  (`~/.claude`) — ou apontar `CLAUDE_CONFIG_DIR` para um volume.
- Aceitar que a credencial **expira**. A falha precisa ser visível: hoje ela cai
  em `erros` e o post volta para a fila na rodada seguinte, silenciosamente,
  para sempre. Vira um check (§8: `fila_extracao_nao_cresce`).
- É a mesma conta e o mesmo uso de hoje, em outra máquina — não muda a natureza
  do uso, muda o hospedeiro. **O autor autorizou** (14/08), então o passo entra
  no escopo do servidor.

**Os planos B, em ordem de preferência.** O risco aqui nunca foi de permissão,
e sim de a credencial não sobreviver — login que expira, container que perde o
diretório, headless que pede interação:

1. **Manter só este passo local**, agendado. A fila é incremental e re-tentável
   por desenho; ficaria uma `--rodada-local` minúscula, e todo o resto no
   servidor. É o plano B mais barato e o que não exige tocar em código.
2. **Trocar o `claude -p` pela CLI do Codex**, que o autor também assina.
   Funciona, mas **não é substituição de uma linha**: muda o binário, muda o
   formato de saída (`codex exec` emite eventos, não o `--output-format json`
   que o parser espera hoje) e muda o modelo — e o prompt de extração foi
   calibrado contra flyers reais, com uma guarda de confiança que decide se um
   evento é criado ou descartado. Trocar exige **revalidar a extração contra um
   lote de flyers já processados** e comparar o resultado, senão a troca degrada
   a qualidade do dado em silêncio, que é a classe de erro que esta spec inteira
   tenta acabar. Vale como plano B de verdade, não como atalho.

A ordem importa: (1) preserva o comportamento medido; (2) é uma mudança de
qualidade de dado disfarçada de mudança de infraestrutura.

**Sugestão de sequência:** implementar a extração de flyer por ÚLTIMO (fatia 5).
Se ela emperrar, tudo o mais já estará rodando, e o que sobra é exatamente a
`--rodada-local` de hoje, só que menor.

### 6.5 Playwright/Chromium

O Shotgun devolve 0 no runner do Actions e 65–71 eventos na máquina do autor
(NI-58, medido em 26–28/07). A hipótese é bloqueio por origem — o homelab está
no mesmo IP residencial que funciona hoje, então a expectativa é que passe a
funcionar. **Não é certeza**: o navegador vai estar headless num container
Linux, não no Windows do autor. É a primeira coisa a testar na fatia 4, e o
scraper já falha alto (listagem sem slug levanta exceção e despeja HTML +
screenshot em `diagnostico/shotgun/`) — o diagnóstico já vem pronto.

⚠️ **Antes disso vem um obstáculo mais bobo, previsto na fatia 2 e a resolver na
4: o container roda como `root`, e o Chromium recusa subir como root sem
`--no-sandbox`.** Hoje `coleta/shotgun.py:108` chama
`p.chromium.launch(headless=True)` e nada mais — no Windows do autor isso é
irrelevante, no container é uma falha imediata (`Running as root without
--no-sandbox is not supported`), que o scraper vai reportar como listagem
vazia... não: ele levanta exceção, que é o comportamento certo, mas o motivo
não terá nada a ver com bloqueio de origem. As saídas, em ordem: acrescentar
`args=["--no-sandbox"]` no launch quando o processo estiver rodando como root,
ou criar um usuário não-root na imagem (mais correto, mais caro — os bind
mounts do clone e do `~/.claude` passam a precisar de dono compatível). A
decisão fica para a fatia 4, junto do teste de verdade; o que não pode é essa
falha ser confundida com o NI-58.

### 6.6 Compute logs: o pipeline inteiro fala por `print`

O `instance.info` mostra `compute_logs: NoneType`, e o `dagster.yaml` de fato
não configura nada — mas isso **não** quer dizer desligado: o default do
Dagster é o `LocalComputeLogManager`, que grava `stdout`/`stderr` em
`$DAGSTER_HOME` e os mostra na UI.

> Correção de uma leitura anterior desta spec: os `print` **aparecem**. O
> problema é outro, e é de arranjo, não de configuração.

Dois problemas reais, ambos resolvidos pela §6.0:

1. **O log é gravado no disco do container que rodou** e lido pelo container do
   webserver. Sem o `/opt/dagster/home` compartilhado, a UI mostra run bem
   sucedido com aba de log vazia.
2. **É efêmero.** `/opt/dagster/home` não tem volume hoje: o relatório de saúde
   de todas as rodadas some no próximo rebuild. Aceitável (a fonte da verdade é
   `operacao.execucoes`, §9), desde que consciente.

Independente disso, uma mudança de código: **promover o que é sinal a
`context.log` e a metadata** — alerta de queda, payloads rejeitados, sumidos,
feedback não lido. `print` serve ao relatório narrativo; não serve para o que
deve disparar alarme, porque texto em log não vira estado (§8).

---

## 7. Agendamento, concorrência e custo

### 7.1 Schedule

Um schedule diário do job `rodada_diaria` às **03:00 America/Sao_Paulo** —
mesmo horário efetivo de hoje (`0 6 * * *` UTC), agora pontual e sem fila de
CI. Ganho colateral: acaba a armadilha do GitHub de desativar workflow agendado
após 60 dias de inatividade.

Cadências diferentes por asset (ex.: Shotgun a cada 3 dias, cinema toda quinta
quando a programação vira) são **possíveis e tentadoras** — deixar para depois
da migração, com dado da série histórica na mão. Uma cadência por asset
multiplica os modos de falha e não há medição hoje que justifique.

### 7.2 Concorrência: onde está o ganho e onde está o risco

**Ganho:** as cinco fontes rodam em série hoje (~440 s) e são independentes. Com
o executor multiprocess, o caminho crítico vira o Shotgun (230 s) — ~3,5 min por
rodada. `descrever`/`precificar` são o gasto maior e também poderiam paralelizar
por fonte; ficam para depois (a fila hoje é cross-fonte e mexer nela é mudar
comportamento).

**Risco:** paralelismo sem limite é como se toma 429 de fonte e se estoura
conexão no Neon. Três diques:

| Dique | Onde | Valor sugerido |
|---|---|---|
| `max_concurrent_runs` | `dagster.yaml`, run coordinator | 1 — duas rodadas na mesma base é o que a `concurrency` do Actions já evitava |
| Pool `rede` | `@asset(pool="rede")` nas coletas | 3 |
| Pool `visao` | `cru/extracao_flyer` | **1** — a visão é serial por natureza (~60 s/post) e é cota de assinatura |
| `max_concurrent` do executor | job | 4 |

### 7.3 Custo, que era o motivo nº 3

O que hoje não é medido e passa a ser, como metadata numérica por materialização
(o Dagster plota série histórica de metadata numérica):

- **tempo** por asset (já existe por fonte em `operacao.coletas`; passa a existir
  por passo, incluindo descrever/precificar/visão);
- **requisições** por passo — hoje só se sabe "quantas descrições foram
  buscadas"; o número de chamadas HTTP por rodada não existe em lugar nenhum;
- **dinheiro do Monid**: `perfis × $0,006` por rodada, o primeiro custo
  recorrente do projeto, hoje estimado de cabeça;
- **cota de visão**: posts extraídos e segundos gastos;
- **TMDB**: chamadas por rodada (incremental, deve ser ~0 em regime).

Isso não reduz custo sozinho — dá a série que permite decidir, por exemplo, se
vale raspar o Ticket and Go inteiro todo dia (197 s para ~70 eventos de DF num
catálogo nacional de 37 páginas).

---

## 8. Asset checks — a tradução do que hoje é `print`

Cada check abaixo já existe como regra no código ou como linha do relatório. A
migração não inventa qualidade nova: ela **transforma texto em estado**.

| Check | Asset | Regra | Severidade | Origem hoje |
|---|---|---|---|---|
| `coleta_nao_falhou` | cada `cru/<fonte>` | `erro IS NULL` na coleta desta rodada | **ERROR** | `resultados[nome]["erro"]` no relatório |
| `coleta_nao_zerada` | cada `cru/<fonte>` | `coletados > 0` | **ERROR** | guarda NI-59 (SQL do `sumido`) |
| `sem_queda_abrupta` | cada `cru/<fonte>` | `coletados >= 50%` da rodada anterior | WARN | alerta `QUEDA_ALERTA` do relatório |
| `cobertura_do_catalogo` | cada `cru/<fonte>` | `coletados / total_site` acima do piso | WARN | linha "coletados/total no site" |
| `codigo_atualizado` | `operacao/execucao` | SHA local == `origin/main` | WARN | **não existe** — o buraco do §1.3(b) |
| `sem_payload_rejeitado` | `tratado/eventos` | `derivado["rejeitados"] == []` | **ERROR** | bloco `*** payload(s) REPROVADOS` |
| `eventos_futuros_por_fonte` | `tratado/eventos` | toda fonte com coleta boa tem ≥1 futuro | WARN | "janela futura por fonte" |
| `datas_normalizadas` | `tratado/eventos` | `start_date`/`raspado_em` casam o invariante ISO UTC | **ERROR** | invariante do upsert, hoje sem verificação |
| `frescor_por_fonte` | `tratado/eventos` | `max(raspado_em)` de cada fonte < 48 h | **ERROR** | **não existe** — pegaria os 7 dias do Sympla |
| `pico_de_sumidos` | `tratado/eventos` | sumidos da rodada < N% dos futuros da fonte | WARN | lista de sumidos no relatório |
| `completude` | `tratado/eventos` | % com descrição e % com `preco_min` por fonte | WARN | duas seções do relatório |
| `grade_completa` | `tratado/sessoes` | 8 cinemas presentes e `sessoes > 0` | WARN | "Cinema: N filmes, M sessões" |
| `watchlist_coberta` | `cru/instagram` | perfis coletados == perfis ativos | WARN | "coletados/total_site" do Instagram |
| `fila_extracao_nao_cresce` | `cru/extracao_flyer` | pendentes ≤ pendentes da rodada anterior | WARN | aviso `*** N posts aguardando extração` |
| `feedback_lido` | `operacao/execucao` | não há feedback não lido há > 7 dias | WARN | `*** N feedback(s) não lido(s)` |

**Nenhum check é `blocking`.** Bloquear o downstream faria o tratamento não
rodar quando uma fonte falha — o oposto de "uma fonte quebrada não esconde as
outras" (D6). Checks aqui são **alarme**, não portão. A única candidata a
`blocking` seria `sem_payload_rejeitado`, e mesmo essa não: a prata já é
reconstruída sem o payload ruim, e travar a rodada por causa dele deixaria a
base velha em vez de correta-e-incompleta.

### 8.1 Freshness policy: o alarme que funciona com o servidor desligado

Um check só reprova se o run acontecer. Se o homelab estiver desligado, ou o
schedule não disparar, **nenhum check fica vermelho** — o sistema fica quieto,
exatamente como ficou entre 12 e 14/08.

`FreshnessPolicy` cobre esse caso, porque é avaliada pelo daemon (que já roda,
`FRESHNESS_DAEMON: healthy`) contra a última materialização:

```python
@dg.asset(..., freshness_policy=dg.FreshnessPolicy.time_window(
    fail_window=timedelta(hours=30), warn_window=timedelta(hours=26)))
```

Aplicar em `tratado/eventos` (a materialização que representa "a base está em
dia") e, com janela mais larga, em `cru/shotgun` e `cru/instagram`. Há também a
variante por cron (`deadline_cron` + `lower_bound_delta`), que casa melhor com
schedule fixo — conferir a assinatura exata na 1.13 ao implementar.

**Buraco honesto:** a freshness policy fica vermelha na UI, e o Dagster OSS
**não tem alertas** (e-mail/Slack são do Dagster+). Se o servidor cair, quem
avisa?

**O `n8n` já está no ar no mesmo homelab** (`n8n/docker-compose.yml`, porta
5678, `restart: unless-stopped`) — e ele existe exatamente para isto. A saída
deixa de ser "escrever um integrador" e passa a ser cinco linhas de cada lado:

1. um `@run_failure_sensor` e um sensor de freshness no Dagster fazem um `POST`
   num **webhook do n8n**;
2. o fluxo do n8n decide o canal (Telegram, e-mail, o que o autor já usar) e
   pode agregar, silenciar repetição e formatar.

Duas ressalvas que impedem a solução de ser redonda:

- **os dois estão na mesma máquina.** Se ela cair, o alarme cai junto — é o
  cenário que mais importa. Cobrir isso de verdade exige um vigia **de fora**:
  um cron do Actions (que continua existindo, D3) consultando o frescor da base
  e falhando se estiver velho, ou um monitor externo batendo numa rota do site.
  É a variante (2) abaixo, e ela vale mais que o sensor;
- as stacks são projetos Compose separados, com redes próprias: o Dagster
  alcança o n8n pelo IP do host + 5678, não por `http://n8n:5678`. Detalhe
  bobo que custa uma tarde quando não está escrito.

A variante (2) segue valendo por si: **o próprio site expor o frescor** (a base
já tem `operacao.execucoes`; um canto discreto do `/sobre` com "atualizado há
X" serve ao leitor e é um vigia que roda na Vercel, fora do homelab).

Recomendo o sensor → n8n como fatia própria depois da migração, e o vigia
externo junto — sem ele, o alarme compartilha o destino do que deveria vigiar.

---

## 9. O que substitui o relatório de saúde

Nada — ele continua (D11). O asset `operacao/execucao` chama
`passos.relatorio(...)` e `execucoes.registrar_execucao(...)` exatamente como
hoje, com os mesmos números e o mesmo formato de `operacao.execucoes`.

O que muda é que ele deixa de ser a ÚNICA superfície. A informação passa a
existir em três lugares, com propósitos distintos:

| Superfície | Serve para | Persistência |
|---|---|---|
| `operacao.execucoes` + relatório | a leitura narrativa do autor; a comparação vs. rodada anterior | a base (permanente) |
| Metadata de asset | série histórica, gráficos de tempo/custo | event log do Dagster (Postgres do homelab) |
| Asset checks + freshness | estado: verde/amarelo/vermelho | event log do Dagster |

⚠️ **O event log do Dagster é do homelab e não tem backup.** Não é fonte da
verdade de nada — `operacao.*` continua sendo. Se a instância for recriada, a
série histórica de metadata se perde e a base não sente. Ter isso escrito evita
a tentação de mover telemetria para lá.

---

## 10. Segurança

O `docs/DAGSTER.md` já registra: **a instância não tem autenticação**. Quem
alcança a tailnet consulta, dispara e mata execuções. Enquanto a tailnet é só do
autor, o risco é o de sempre; a migração muda o que está em jogo:

- passa a haver **credencial da base de produção** (`EVENTOS_DB_URL`) e
  **credencial da assinatura Claude** no ambiente daquele container;
- o run coordinator aceita **launch de qualquer origem na tailnet**;
- config de run e logs ficam legíveis na UI.

Medidas mínimas antes de a migração ir a sério:

1. **Confirmar que continua `tailscale serve` e nunca vira `funnel`** — o doc já
   avisa que a porta 8443 é uma das três do Funnel e que nenhum teste feito de
   dentro distingue os dois. `tailscale serve status` na máquina é o juiz.
2. **ACL do Tailscale** se a tailnet passar a ser compartilhada.
3. **Segredo só por `env_file`**, nunca por config de run (§6.3).
4. Considerar um usuário de banco com permissão restrita a `cru`/`operacao`/
   `tratado` — hoje o pipeline usa a mesma URL do site. Fora de escopo da
   migração, vale como item separado.

---

## 11. Riscos

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Homelab cai (energia, internet, disco) | média — **sem no-break** (§15) | base envelhece em silêncio | Actions como fallback (D3) + freshness policy + a notificação da §8.1 + `dagster/max_runtime` para o run zumbi (ver a linha abaixo) |
| O login da assinatura não sobrevive no servidor | média (autorizado, mas não testado) | extração de flyer continua local | Fatia 5 por último; dois planos B na §6.4, sendo o primeiro sem custo de código |
| Shotgun também falha headless no Linux | média | continua como está hoje | Testar na fatia 4; o scraper já despeja diagnóstico |
| Refactor de `passos.py` muda comportamento sem querer | média | dado errado na base | §13: comparação antes/depois em `--so-derivar` + suíte + rodada comparada |
| Código do clone defasado (a doença do §1.3b, de novo) | **alta** | roda-se o código errado | `git pull` no início do job + SHA em metadata + check `codigo_atualizado` |
| Dagster vira dependência do pipeline por conveniência | média | perde-se o rollback e o teste barato | D5, escrito no CLAUDE.md |
| Versão do `dagster` na code location ≠ do daemon | **alta** (o `pip install` do homelab não tem pin) | erros obscuros de serialização | pinar a MESMA versão exata nos dois Dockerfiles, subir junto (§6.1) |
| Config do repositório não chega ao container | **MEDIDA na fatia 0** | `dagster.yaml` novo não vale e nada avisa | bind mount de DIRETÓRIO no `DAGSTER_HOME` — bind mount de arquivo é preso ao inode e `git pull` o substitui (§6.0) |
| Run travado fica `STARTED` para sempre | **MEDIDA na fatia 0** | a rodada some sem falhar; o alarme de frescor é o único a perceber | `dagster/max_runtime` em TODO job: `run_monitoring` não detecta worker morto com o `DefaultRunLauncher` (§6.0) |
| Alarme mora na mesma máquina que ele vigia | **certa** | queda do homelab não avisa ninguém | vigia externo (Actions ou site), além do sensor → n8n (§8.1) |
| Perda do `pg-data` do Dagster | baixa | some a série histórica de custo/tempo | é o motivo nº 3 da migração morando sem backup: um `pg_dump` semanal resolve (§9) |
| Chromium + 5 fontes consomem o servidor | baixa | outros serviços do homelab sofrem | limites de concorrência (§7.2); medir na fatia 4 |
| Log do run invisível na UI (disco não compartilhado) | **certa, se não tratada** | rodada "verde" com aba de log vazia | §6.0/§6.6 — o `./home` compartilhado é parte da fatia 0 |
| Raspagem rodar dentro do webserver e derrubar a UI | **certa, sem a §6.0** | UI cai junto com um pico de memória do Chromium | serviço `raspador_code` dedicado |

---

## 12. Fatias

Cada fatia termina com algo verificável e reversível. As fatias 0–3 não tocam em
nada que esteja em produção hoje.

> **Regra de execução desta spec — combinada em 14/08.** Diferente das últimas
> specs, aqui **nenhuma fatia começa antes de a anterior estar testada, validada
> pelo autor e marcada como feita**. Cada fatia tem dois checklists: o **✅ meu**
> (verificação que eu rodo e colo o resultado) e o **👤 teu** (conferência
> humana, que só o autor pode dar). O portão de cada fatia exige os dois
> completos. Se um item falhar, a fatia não avança — corrige-se e repete-se o
> checklist inteiro, não só o item que falhou.
>
> **🔑 marca o que depende de você executar**, mesmo dentro do meu checklist —
> ver a §12.0, que explica por quê e junta tudo numa lista só.
>
> Marcar o progresso aqui mesmo, nesta tabela, à medida que cada fatia fecha:

| Fatia | Onde | ✅ meu | 👤 teu | Feita em |
|---|---|---|---|---|
| 0 — compose | `homelab` | ✅ | ✅ | **14/08/2026** |
| 1 — `passos.py` | `raspador_eventos` | ✅ | ✅ | **17/08/2026** |
| 2 — imagem do raspador | ambos | ✅ | ✅ | **17/08/2026** |
| 3 — grafo em `eventos_teste` | `raspador_eventos` | ☐ | ☐ | |
| 4 — Shotgun e produção | ambos | ☐ | ☐ | |
| 5 — Instagram completo | ambos | ☐ | ☐ | |
| 6 — checks e freshness | `raspador_eventos` | ☐ | ☐ | |
| 7 — desligar o Actions | `raspador_eventos` | ☐ | ☐ | |

---

### 12.0 O que só o autor pode fazer

**Eu não tenho shell no servidor.** O único acesso que tenho ao homelab é o
GraphQL do Dagster pela tailnet — POST, sem autenticação, o que a `docs/DAGSTER.md`
descreve. Com ele eu consulto estado, disparo e acompanho runs, leio logs e
checks. **Não** consigo: rodar `docker`, editar arquivo no servidor, clonar
repositório, instalar coisa, fazer login interativo, olhar o systemd.

Isso divide o trabalho de um jeito que precisa estar escrito, senão a cada fatia
paramos para descobrir de novo: **eu escrevo os arquivos e digo o comando exato;
você executa no servidor e cola a saída.** Onde isso acontece, o item vem
marcado com 🔑.

> **Atalho que elimina a maior parte do vaivém, se você quiser:** rodar o Claude
> Code na própria máquina do servidor (ou por SSH a partir dela) durante as
> fatias 0, 2, 4 e 5. Aí os itens 🔑 de execução viram meus, e sobram só os de
> segredo e login. É uma escolha sua — a spec funciona dos dois jeitos, só muda
> o número de idas e vindas.

#### As ações manuais, na ordem em que aparecem

| # | Quando | O que você faz | Por que só você |
|---|---|---|---|
| 1 | antes da fatia 0 | **Decidir os caminhos no servidor**: onde fica o clone do raspador (a spec sugere `/srv/raspador_eventos`) e onde fica o `env_file` | é o layout da sua máquina |
| 2 | antes da fatia 0 | **`git clone`** do `raspador_eventos` nesse caminho | acesso ao servidor |
| 3 | fatia 0 | **Criar o `env_file`** e colar os segredos: `EVENTOS_DB_URL`, `EVENTOS_DB_URL_TESTE`, `TMDB_API_KEY`, `BLOB_READ_WRITE_TOKEN`, `FORCAR_IPV4=1` | são credenciais; **nunca passam por mim, por commit, nem pelo launchpad do Dagster** (§6.3, §10) |
| 4 | fatia 0 | Conferir que esse arquivo está **fora do git** (o `.gitignore` do homelab já ignora `.env`; se o nome for outro, acrescentar) | um segredo commitado num repo público não se desfaz |
| 5 | fatia 0 | Aplicar os arquivos que eu escrever (compose, Dockerfile, `dagster.yaml`, `workspace.yaml`) e rodar **`docker compose up -d --build`** | acesso ao servidor |
| 6 | fatia 0 | Rodar os comandos 🔑 do checklist e colar a saída | idem |
| 7 | fatia 0 | **`tailscale serve status`** — confirmar serve, não funnel | só se responde na máquina |
| 8 | fatia 0 | **Commitar no repo `homelab`** (eu não commito em repo nenhum sem seu ok, e nesse eu nem tenho por onde) | é seu repositório |
| 9 | fatia 2 | **`monid keys add -k <chave> -l main`** dentro do container/volume do monid | a chave é sua e mora no config do monid, não no repo |
| 10 | fatia 2 | Build da imagem e os testes 🔑 dentro do container | acesso ao servidor |
| 11 | fatia 4 | **Trocar o `env_file` de `eventos_teste` para produção** e reiniciar o serviço | é a virada de chave da migração; melhor ser um gesto humano e consciente |
| 12 | fatia 4 | Decidir a alternância de dias com o Actions (eu consigo ligar/desligar o workflow pelo `gh`, mas a decisão é sua) | julgamento |
| 13 | fatia 5 | **Login do `claude` no servidor**, uma vez, interativo — e renovar quando expirar | credencial da sua assinatura; é interativo por natureza |
| 14 | fatia 6 | **Calibrar os limiares** dos checks (piso de cobertura, % de sumidos, janela de frescor) | julgamento sobre o que é normal na sua base |
| 15 | qualquer momento | **`pg_dump` semanal do `dagster_pg`** — agendar no servidor | acesso ao servidor; e é o backup que hoje não existe (§11) |
| 16 | opcional, fora do escopo | **Usuário só-leitura no Neon** para o metabase, se ele for apontar para lá (§15) | console do Neon |
| 17 | opcional | **No-break** — a única falha física sem mitigação (§15) | compra |

**O que eu faço sozinho, para contraste:** escrever todo o código e os arquivos
de configuração, consultar e disparar runs pelo GraphQL, ler logs e checks,
rodar a suíte de fumaça e as comparações de dado daqui, mexer no `gh` do
Actions, e produzir os diffs para você revisar.

---

### Fatia 0 — reestruturar o compose

**Onde:** repo `homelab`, pasta `dagster/`. Não toca no raspador.
**Pré-requisitos seus** (§12.0, itens 1–4): caminhos decididos, `git clone` do
raspador feito no servidor, `env_file` criado com os segredos e conferido fora
do git. Sem os quatro, a fatia não começa — o `raspador_code` sobe e morre no
primeiro import.
**O quê:** serviço `raspador_code` (ainda com a imagem atual, magra); `./home`
bind-montado nos quatro serviços, com `dagster.yaml`/`workspace.yaml` dentro
(§6.0); `dagster==1.13.17` pinado no Dockerfile existente; `max_concurrent_runs:
1`, pools (§7.2) e `run_monitoring` no `dagster.yaml`.

**Feita em 14/08/2026.** Commits no `homelab`: `429d475` (o arranjo),
`c1a280e` + `8564117` (cobaias de teste e sua limpeza), `5407afc` (a correção
que o teste forçou).

**✅ Meu checklist**

- [x] 🔑 `docker compose config` valida sem erro e mostra os quatro serviços.
- [x] 🔑 `dagster --version` **idêntica** nos três containers (webserver, daemon,
      `raspador_code`) — é o risco da §6.1. → 1.13.17 nos três.
- [x] A code location `raspador` aparece como `LOADED` na consulta GraphQL
      (`repositoriesOrError`), servida por gRPC e não por `python_file`.
- [x] `hello_homelab` migrado para a code location nova materializa **pelo botão**
      e o `print` aparece na aba de log. → run `e5dc9e00`, SUCCESS.
- [x] O mesmo asset materializa **por schedule** e o `print` também aparece — é o
      teste do disco compartilhado, e só ele prova que webserver e daemon
      enxergam o mesmo disco. → run `4edbf3c7`, mesmo container (`1cb159a1fd2c`
      = `raspador_code`), stdout legível pelo webserver.
- [x] 🔑 **Teste da armadilha do `DAGSTER_HOME`:** mudar um valor visível no
      `dagster.yaml`, reiniciar, e conferir o valor novo. **FALHOU na primeira
      forma** e é o achado principal da fatia — ver a §6.0. Passou depois de o
      mount virar diretório: `maxConcurrentRuns` foi a 2 e voltou a 1.
- [x] 🔑 **Teste do run travado.** O item original dizia "`docker kill` no meio de
      um run e conferir que ele termina como `FAILURE`" — e estava **errado**:
      `run_monitoring` não detecta worker morto com o `DefaultRunLauncher`.
      Medido: o run ficou `STARTED` por mais de 5 min depois de o processo
      morrer, e ficaria para sempre. Com `dagster/max_runtime: 60`, o mesmo run
      virou `FAILURE` em ~100s, com a mensagem "Canceling due to exceeding
      maximum runtime of 60 seconds". **Consequência para o resto da spec:** a
      tag passa a ser obrigatória em todo job, não opcional.
- [x] O schedule de teste é removido ao final. → `8564117`.

**👤 Teu checklist**

- [x] Abrir a UI e ver a code location `raspador` na lista, sem erro vermelho.
- [x] Clicar "Materialize" no `hello_homelab` e ver o log aparecer na tela.
- [x] Confirmar que a UI seguiu respondendo enquanto o run acontecia.
- [x] Rodar `tailscale serve status` na máquina e confirmar **serve**, não funnel
      (§10.1) — é a reconferência que a spec pede a cada mexida no compose.
- [x] Dar o ok no diff do `homelab` antes do commit.

**Portão:** os dois checklists completos. Sem isto, a fatia 1 não começa. ✅

> **Três coisas que a execução ensinou, e que valem além desta fatia.**
> 1. Bind mount de arquivo é preso ao inode — a config do repo não chegava ao
>    container (§6.0). Vale para qualquer arquivo montado individualmente daqui
>    para a frente.
> 2. `run_monitoring` + `DefaultRunLauncher` não fecha run órfão. Só o teto de
>    duração fecha.
> 3. `docker kill` é tratado pelo Docker como **parada manual**: o
>    `restart: unless-stopped` não religa o container depois dele. A política
>    vale para container que morre por conta própria — o caso da queda de
>    energia. A simulação foi mais dura que o cenário real, e o veredito sobre o
>    run vale igual.

---

### Fatia 1 — `passos.py`, sem Dagster

**Onde:** repo `raspador_eventos`, `src/pipeline/`. Nenhum Dagster envolvido.
**O quê:** o refactor de movimentação da §5.2, com o `atualizar.py` intacto em
comportamento.

**✅ Meu checklist** — feito em 14/08/2026, com o resultado de cada item:

- [x] `--so-derivar` **antes** do refactor, saída guardada em arquivo.
- [x] `--so-derivar` **depois**, e `diff` das duas saídas: as contagens de
      `derivado`, `enriquecimento`, `sumidos` e `slugs` são idênticas, e o
      conjunto de nomes listados (sumidos, ruído, grupos de dedupe) também —
      `diff` dos dois arquivos ordenados sai vazio. O que difere é timestamp,
      duração, a ORDEM das listagens (query sem `ORDER BY`, não determinismo
      pré-existente) e as contagens de "eventos futuros", porque os cinco
      minutos entre as duas rodadas jogaram eventos do dia para o passado.
- [x] Suíte de fumaça inteira verde — os oito scripts, com `test_bronze`
      (apaga a prata e reconstrói) por último.
- [x] `grep -r "import dagster" src/` → **vazio** (D5).
- [x] `python src/ferramentas/linhagem.py` roda; o diff em `docs/linhagem/` é
      16 linhas, todas a mesma coisa: onde se lia `pipeline/atualizar.py` como
      leitor de uma tabela, agora se lê `pipeline/passos.py`. É o refactor
      aparecendo no mapa — o CLI não faz mais SQL nenhum.
- [x] `git diff --stat`: `atualizar.py` −718/+50, `passos.py` +769. Comparação
      função a função (AST, com os renomes aplicados): **onze das treze funções
      movidas são byte-idênticas**; as duas que diferem, só em comentário —
      `precificar` (uma menção a `_descrever`) e `relatorio` (a chamada a
      `coleta_anterior` e um comentário que citava o antigo `_marcar_sumidos`).
      As mudanças de forma são as duas declaradas na §5.2, e nenhuma outra.
- [x] Uma rodada `completo` local (execução #47, 36 min): sympla 274→271,
      ingresse 3→2, zig 1→3, ticketandgo 70→73, shotgun 74/74, cinema 8/8,
      instagram 5/5 — **nenhum alerta de queda**. 57 flyers extraídos sem falha,
      12 filmes no TMDB, 12 pôsteres. `operacao.execucoes` gravou no formato de
      sempre, com `fontes[nome].coletados` intacto — é dele que o alerta de 50%
      se alimenta, e é o que quebraria em silêncio se o D8 tivesse escorregado.

**👤 Teu checklist**

- [x] Ler o diff de `passos.py` × `atualizar.py` — é a fatia com risco real de
      mudar comportamento sem querer.
- [x] Rodar você mesmo `python src/pipeline/atualizar.py --so-derivar` e ver o
      relatório sair igual ao que você conhece.
- [x] Conferir que a única quebra de forma é a que a §5.2 declara
      (`_raspar` vira `coletar` de UMA fonte).
- [x] Ok para commitar. → **revisado em 17/08/2026.**

**Portão:** os dois checklists completos.

---

### Fatia 2 — a imagem do raspador

**Onde:** `homelab` (compose) + `raspador_eventos` (o Dockerfile, que mudou de
repositório — §6.2 — e o `definitions.py` com um asset só).
**O quê:** o `raspador_code` passa a usar imagem própria — `requirements.txt`,
Node + Monid, Chromium, `claude` —, com o clone git montado, `PYTHONPATH`,
`env_file` e `FORCAR_IPV4=1`. Um asset trivial que consulta
`SELECT count(*) FROM tratado.eventos`.

**Escrito em 17/08, antes de o servidor entrar:**

- `docker/raspador_code.Dockerfile` — `python:3.12-slim` + Node 22 (NodeSource)
  + `@monid-ai/cli` + `@anthropic-ai/claude-code` + `dagster==1.13.17` pinado
  igual ao webserver + `requirements.txt` + `playwright install --with-deps
  chromium`. Mais `git` (o SHA da §6.2) e `tzdata` (sem ele o
  `TZ=America/Sao_Paulo` não resolve e o dia local de Brasília viaja).
- `.dockerignore` — contexto de build reduzido ao `requirements.txt`.
- `src/pipeline/definitions.py` — o asset `tratado/contagem_eventos`, que só
  lê. Ele importa `passos` **de propósito**: é o import que aplica o
  `FORCAR_IPV4` e é ele que puxa a cadeia inteira (coleta, tratamento,
  serviço), de modo que dependência faltando na imagem apareça como code
  location vermelha, e não no meio da primeira rodada de produção.
- Compose do `homelab`: `build.context` apontando para o clone, `working_dir`,
  `DAGSTER_HOME`, os volumes do clone e do `~/.claude`, e o `-f` do gRPC agora
  no `definitions.py` do raspador. O `hello_homelab` sai da UI — a pasta
  `./pipelines` deixa de ser montada.
- **Ensaio local do asset** (venv com `dagster==1.13.17`, `dg.materialize`):
  materializou contra produção em leitura — `base=eventos`, 968 eventos, 343
  futuros, conexão em 0,20 s. Achado: `conectar()` devolve `row_factory=
  dict_row`, então `fetchone()[0]` estoura `KeyError: 0` — toda contagem
  precisa de apelido (`count(*) AS n`). Teria sido a primeira materialização
  vermelha na UI.
- `linhagem.py` regravado: o gerador enxergou o `definitions.py` sozinho e já o
  lista como leitor de `tratado.eventos`.

**Executado no servidor em 17/08.** Uma coisa quebrou, e é a que vale
registrar: **o git dentro do container recusava o clone montado** —
`detected dubious ownership in repository at '/opt/raspador'`, porque o
diretório é do usuário do host e o container roda como root. Não atrapalha
nada hoje, e é exatamente por isso que era perigoso: o SHA do run — o que a
§6.2 pede para desfazer a doença do bind mount — sairia vazio sem nada na tela
dizendo por quê. Resolvido na imagem (`git config --system --add
safe.directory`, commit `7eb5508`), e não com um `git config` avulso dentro do
container, que sumiria no rebuild seguinte.

**✅ Meu checklist**

- [x] 🔑 Imagem builda; tamanho final reportado na conversa (para você decidir se
      incomoda). → **458 MB**, com o Chromium dentro (`/opt/playwright` tem
      `chromium-1234`, `chromium_headless_shell-1234`, `ffmpeg-1011`). Não
      incomoda — não há motivo para separar a imagem que serve a code location
      da que executa a raspagem.
- [x] 🔑 Dentro do container: `import psycopg`, `playwright --version`,
      `node --version`, `monid --version` — todos respondem. → node v22.23.2,
      monid 0.1.6, claude 2.1.233, playwright 1.62.0, imports ok.
- [x] 🔑 `dagster --version` continua idêntica à do webserver. → **1.13.17** nos
      dois.
- [x] 🔑 `git rev-parse HEAD` dentro do container == SHA do repo local (a
      partir da fatia 3 isso vira metadata de run e deixa de ser manual). →
      só depois do `safe.directory`; hoje `7eb5508` dos dois lados.
- [x] A code location carrega o `definitions.py` **do repo do raspador** (não de
      `homelab/dagster/pipelines/`).
- [x] O asset trivial materializa contra a base de **produção em leitura**, e o
      número bate com `SELECT count(*)` rodado daqui. → run `636d97a3`:
      `base=eventos`, 968 eventos, 343 futuros — os mesmos números do ensaio
      local. Conexão em 0,36 s (0,20 s aqui): o servidor está um pouco mais
      longe do Neon, e isso é irrelevante numa rodada de minutos.
- [x] 🔑 **Teste de rede/Neon:** tempo de abertura da conexão medido com e sem
      `FORCAR_IPV4=1`. Se a diferença for grande, a variável fica; se não,
      registro na spec que a rede do servidor não precisa dela. → **a rede do
      servidor não precisa dela**; a variável fica como cinto de segurança.
      Números, e o falso positivo que a primeira leitura produziu, na §6.3.
- [x] Nenhum segredo aparece na UI (conferir a aba de config do run). → aba
      Configuration do run vazia; os segredos entram só pelo `env_file`.

**👤 Teu checklist**

- [x] Ver o asset materializar na UI e conferir que o número bate com o que o
      site mostra.
- [x] Conferir que a UI seguiu responsiva com o container pesado no ar.
- [x] Conferir que o `env_file` está fora do git (`git status` no `homelab`).
- [x] Ok no Dockerfile novo. → **revisado em 17/08/2026.**

**Portão:** os dois checklists completos. A partir daqui existe credencial de
produção no servidor — não avançar com pendência de segurança.

---

### Fatia 3 — o grafo, contra `eventos_teste`

**Onde:** `raspador_eventos`, `definitions.py`.
**O quê:** assets das 4 fontes leves + detalhes/tickets + cinema + o
`@multi_asset` do tratamento, com `EVENTOS_DB_URL` apontando para
`eventos_teste`. Job e schedule **desligados** — só materialização manual.

**✅ Meu checklist**

- [ ] `EVENTOS_DB_URL` do container aponta para `eventos_teste` — conferido
      dentro do container, não presumido.
- [ ] Materialização completa do grafo termina sem erro.
- [ ] Comparação com `atualizar.py` na mesma base: `count(*)` e
      `max(raspado_em)` por fonte, e `tratado.eventos` linha a linha por `id`.
- [ ] **Teste do D6:** quebrar uma fonte de propósito (URL inválida) e conferir
      que o asset dela materializa com `erro` na metadata, que o run **segue**,
      e que o tratamento roda mesmo assim.
- [ ] **Teste da guarda NI-59:** a fonte quebrada não marca os eventos dela como
      `sumido` (`SELECT count(*) ... WHERE sumido`).
- [ ] Revisão de código: nenhum asset abre transação própria sobre `tratado` —
      só `ciclo.executar` (§4.3).
- [ ] Os três assets do tratamento aparecem separados na UI, com metadata.

**👤 Teu checklist**

- [ ] Olhar o grafo na UI e dizer se ele **explica** o pipeline — é o motivo nº 1
      da migração, e é o único item desta spec que só você pode julgar.
- [ ] Conferir que as chaves com prefixo de camada (`cru/…`, `tratado/…`) fazem
      sentido para você.
- [ ] Ver uma fonte vermelha com o resto verde, e confirmar que é isso que você
      queria ter visto no dia do Sympla.
- [ ] Ok no `definitions.py`.

**Portão:** os dois checklists completos.

---

### Fatia 4 — Shotgun e produção

**Onde:** ambos.
**O quê:** Chromium para valer; `EVENTOS_DB_URL` de produção; schedule diário
ligado. O Actions segue ligado alguns dias, **em dias alternados** — as duas
rodadas na mesma base não se corrompem (a chave é `<fonte>:<id_nativo>`), mas
embaralham a comparação "vs. rodada anterior".

**✅ Meu checklist**

- [ ] Shotgun no container: `coletados > 0` — é o teste do NI-58 e a maior
      incógnita técnica da migração.
- [ ] 🔑 Se falhar: `diagnostico/shotgun/` com HTML e screenshot trazidos para
      análise antes de qualquer conclusão.
- [ ] Primeira rodada de produção completa, com duração por asset registrada.
- [ ] Três rodadas seguidas comparadas com a última do Actions em
      `operacao.execucoes`: coletados por fonte dentro da variação normal.
- [ ] `sumido` não teve pico (o pesadelo do NI-59) — contagem antes e depois.
- [ ] Slugs e FTS íntegros: nenhum evento sem slug, busca por texto responde.
- [ ] O site continua servindo durante a materialização do tratamento (uma
      requisição a `/festas` no meio do run).

**👤 Teu checklist**

- [ ] Abrir o site depois da primeira rodada do Dagster e conferir que a base
      andou — em especial eventos do Sympla e do Shotgun, que estão parados
      desde 07/08.
- [ ] Conferir dois ou três eventos novos no site contra a página da fonte.
- [ ] Olhar o tempo total na UI e dizer se está aceitável.
- [ ] Decidir quando o Actions para de alternar dias.

**Portão:** os dois checklists completos. Esta é a primeira fatia que muda dado
de produção — o rollback é desligar o schedule e religar o Actions.

---

### Fatia 5 — Instagram completo

**Onde:** ambos. Deliberadamente por último (§6.4).
**O quê:** Monid + `claude -p` no servidor.

**✅ Meu checklist**

- [ ] 🔑 `monid` coleta os perfis da watchlist dentro do container; contagem bate
      com `perfis_instagram.yaml`.
- [ ] 🔑 `claude -p` autentica no container e extrai um post novo (o login da
      §12.0 item 13 precisa estar feito antes).
- [ ] **Incrementalidade:** rodar duas vezes e conferir que nenhum shortcode com
      origem `extracao` é reprocessado (é cota de assinatura por tentativa).
- [ ] Custo do Monid da rodada registrado como metadata numérica.
- [ ] Flyers baixados e subidos para o Blob; nenhuma URL de CDN gravada na base
      (a regra de expiração em horas).

**👤 Teu checklist**

- [ ] Pegar **três eventos** criados a partir de flyer nesta rodada e conferir
      nome, data e preço contra o post original no Instagram.
- [ ] Dizer se a qualidade da extração está igual à que você vê rodando local —
      é o item que decide se o passo fica no servidor ou volta para a máquina.
- [ ] Conferir que a credencial não vazou para log nenhum.

**Portão:** os dois checklists completos. Se a qualidade cair, o plano B da
§6.4 (manter só este passo local) entra sem drama — nada mais depende dele.

---

### Fatia 6 — checks, freshness e metadata de custo

**Onde:** `raspador_eventos`, `checks.py`.
**O quê:** os 15 checks da §8, a freshness da §8.1 e a metadata de custo da
§7.3.

**✅ Meu checklist**

- [ ] Cada família de falha provocada ao menos uma vez, e o estado aparece:
      fonte sem rede (`coleta_nao_falhou`), coleta zerada
      (`coleta_nao_zerada`), payload rejeitado (`sem_payload_rejeitado`), clone
      atrasado (`codigo_atualizado`), frescor estourado (`frescor_por_fonte`).
- [ ] **Nenhum check é `blocking`:** com uma fonte vermelha, o tratamento roda
      assim mesmo (D6). Testado, não presumido.
- [ ] Freshness policy avaliada pelo daemon com janela curta temporária, e a
      volta para a janela real conferida.
- [ ] Metadata numérica plotando série histórica na UI (tempo por asset,
      requisições, custo do Monid).

**👤 Teu checklist**

- [ ] Olhar a página de checks e dizer se o vermelho/amarelo comunica o que
      você precisaria saber às 8h da manhã.
- [ ] Calibrar os limiares que são julgamento e não fato: piso de cobertura do
      catálogo, % de sumidos que conta como pico, janela de frescor por fonte.
- [ ] Dizer quais checks você quer que virem notificação depois (§8.1).

**Portão:** os dois checklists completos.

---

### Fatia 7 — desligar o Actions

**Onde:** `raspador_eventos`.
**O quê:** remover o `schedule` do `raspar.yml`, manter o `workflow_dispatch`,
documentar no cabeçalho do arquivo que ele é fallback e como religar.

**✅ Meu checklist**

- [ ] **O fallback é testado, não suposto:** disparar o `workflow_dispatch` à
      mão uma vez, com o schedule já removido, e conferir que a rodada completa
      com sucesso. Um fallback nunca exercitado não é fallback.
- [ ] `CLAUDE.md`, `docs/DAGSTER.md` e o backlog atualizados (NI-58 e o item da
      extração de flyer perdem a razão de existir).
- [ ] `linhagem.py` regravado, se o refactor mexeu no que ele lê.
- [ ] Uma semana de rodadas do Dagster sem intervenção manual, com os números
      de `operacao.execucoes` na conversa.

**👤 Teu checklist**

- [ ] Confirmar a semana sem intervenção — é você quem sabe se teve que mexer.
- [ ] Ler o cabeçalho novo do `raspar.yml` e dizer se, daqui a seis meses e sem
      contexto, ele te diz como religar.
- [ ] Ok final na migração.

**Portão:** os dois checklists completos. Aqui a migração está feita.

---

## 13. Como se prova que não quebrou

Os checklists da §12 dizem **quando** cada verificação acontece; esta seção é o
**porquê** — as quatro comparações de dado que sustentam a afirmação "a
migração não mudou a base". Se algum dia uma fatia precisar ser refeita, é
daqui que se remonta o teste.

1. **Refactor (fatia 1):** `--so-derivar` antes e depois → mesmas contagens em
   `derivado`, `enriquecimento`, `sumidos`, `slugs`. A suíte de fumaça inteira
   (`test_bronze` é a mais importante: apaga a prata e reconstrói).
2. **Grafo (fatia 3):** na base de teste, `atualizar.py` completo vs.
   materialização completa → `SELECT count(*), max(raspado_em)` por fonte,
   `tratado.eventos` linha a linha por `id`.
3. **Produção (fatia 4):** as três primeiras rodadas do Dagster comparadas com a
   última do Actions em `operacao.execucoes` — coletados por fonte dentro da
   variação normal do dia a dia.
4. **Checks (fatia 6):** provocar cada família de falha ao menos uma vez
   (derrubar a rede de uma fonte, forçar um payload rejeitado, atrasar o
   schedule) e conferir que o estado aparece.

---

## 14. Fora de escopo

- Mudar qualquer regra de coleta, tratamento, dedupe ou consulta.
- Particionar assets (D7) e cadências por fonte (§7.1).
- Paralelizar `descrever`/`precificar` por fonte (§7.2) — depois, com medição.
- Mover telemetria de `operacao.*` para o Dagster (§9).
- Notificação externa (§8.1) — dívida registrada, fatia própria.
- dbt, dagster-dbt, IO managers de banco, `dg`/components. O projeto não tem
  transformação SQL declarativa: tem Python que escreve em Postgres numa
  transação. Nada disso ajuda aqui.

---

## 15. Estado das incógnitas

**Respondido em 14/08** pelo `docker-compose.yml` e pelo `dagster.yaml`:

| Pergunta | Resposta | Efeito na spec |
|---|---|---|
| Serviços existentes | webserver + daemon (mesma imagem, `build: .`) + `dagster_pg` | §6.0: falta a code location — é o serviço novo |
| Onde mora o `definitions.py` | bind mount `./pipelines`, mas o `workspace.yaml` está dentro da imagem | §6.0: montar o workspace de fora |
| Disco compartilhado para `DAGSTER_HOME` | **não existe** | §6.0 e §6.6: bind mount de `./home` nos quatro serviços |
| `compute_logs` | não configurado → `LocalComputeLogManager` (default) | §6.6 **corrigida**: os `print` aparecem; o risco é o volume, não a config |
| `run_retries` / concorrência | nada configurado | §7.2: acrescentar `max_concurrent_runs` e pools |
| Fuso | `TZ: America/Sao_Paulo` nos dois serviços | §7.1: o schedule em horário local já casa com a instância |
| Reinício após queda | `restart: unless-stopped` nos três | resolve metade da pergunta 5 — falta o Docker subir no boot |
| Persistência do Postgres do Dagster | bind `./pg-data` | §9: existe em disco, segue **sem backup** |

**Respondido em 14/08** pelo repositório `homelab`:

| Pergunta | Resposta | Efeito na spec |
|---|---|---|
| `Dockerfile` da imagem atual | `python:3.12-slim` + `pip install dagster dagster-webserver dagster-postgres pandas requests`, **sem pin** | §6.1: imagem própria para o raspador, e pinar a versão nos dois |
| Modo de carregamento | `python_file` (in-process), `pipelines/` por bind mount | §6.0 confirmada; e valida o D1 — bind mount de código já é o padrão da casa |
| Onde ficam `dagster.yaml`/`workspace.yaml` | `COPY` para dentro da imagem | §6.0: em `dagster/home/`, montado como diretório — nem `COPY`, nem bind mount de arquivo |
| O que mais roda no homelab | `n8n` (:5678) e `metabase` (:3000, com Postgres local) | §8.1: o alarme tem canal pronto; stacks têm redes separadas |
| Segredos | `.env` gitignorado ao lado do compose (`DAGSTER_PG_PASSWORD`) | §6.3: o padrão da casa já é esse; o raspador entra com `env_file` próprio |
| SO | Linux (bind mounts POSIX, `pg-data` local) | §6.5: Chromium headless em container Linux, como previsto |

**Respondido pelo autor em 14/08** — nenhuma incógnita bloqueia mais a migração:

| Pergunta | Resposta | Efeito na spec |
|---|---|---|
| CPU, RAM, disco | "tem tudo de sobra" | §7.2: os limites de concorrência ficam como estão, mas por causa das FONTES (429) e do Neon, não da máquina |
| 24/7, Docker no boot | **sim** para os dois | §11: some o risco de "esqueceu de subir"; sobra o de energia |
| No-break | **não tem** | §11: é o único ponto de falha físico sem mitigação — ver abaixo |
| IPv6/Neon | "provavelmente sim, mesma rede do notebook" | §6.3: entrar já com `FORCAR_IPV4=1` no `env_file` e conferir na fatia 2 |
| `tailscale serve` | **confirmado `serve`**, não funnel | §10.1 satisfeito; segue valendo como item de reconferência |
| Credencial Claude no servidor | **aceita** | §6.4 deixa de ser o risco alto que era; segue por último (fatia 5) por escolha do autor |
| `metabase` | instalação fresca, não acessa nada; pode apontar para o Neon | §9: painel possível — ver a ressalva de credencial abaixo |

**A queda de energia é o que sobrou.** Sem no-break, um apagão no meio da
rodada mata o run e o Postgres do Dagster junto. Três coisas já previstas
cobrem quase tudo: o `dagster/max_runtime` fecha o run zumbi (fatia 0 — e
medido lá que sem ele o run fica `STARTED` para sempre),
`restart: unless-stopped` + Docker no boot religam sozinhos, e o Actions
continua como fallback (D3). O que **não** está coberto é o `pg-data` sem
backup — apagão não costuma corromper Postgres (o WAL existe para isso), mas o
combinado "sem no-break + sem backup" é o único lugar da migração onde uma
perda seria definitiva. O `pg_dump` semanal da §11 deixa de ser capricho.

**Se o metabase apontar para o Neon, que seja com usuário só de leitura.** É a
mesma recomendação da §10.4, agora com motivo concreto: o metabase é uma
aplicação web com sessão persistente e credencial guardada em disco, no mesmo
host sem autenticação. Um usuário restrito a `SELECT` em `public`/`operacao`
resolve, e não atrapalha painel nenhum — o que se quer ver ali é telemetria,
não escrever.
