# Spec — Arquitetura medalhão: schemas por camada, uma trilha por fonte

> **Status: FATIAS 1–6 IMPLEMENTADAS (2026-07-28); a 7 não.** As duas janelas
> de migração foram executadas em produção, com as três redes e as
> conferências dentro da transação (§9.11 e o commit da fatia 5). O que falta é
> a **inversão do fluxo** — ver o aviso na fatia 7 da §13, que também registra
> o que já está pronto para ela e o que a ausência dela custa.
>
> ⚠️ **O cron da raspagem está DESLIGADO** no GitHub até o push (ver
> `CRON-DESLIGADO.md` na raiz do repo).
>
> **O quê:** reorganizar base e código em camadas explícitas de medalhão —
> `cru` (bronze, o que a fonte disse, **uma tabela por fonte**), `tratado`
> (prata, unificado), `curado` (o que uma pessoa decidiu), `public` (o que site
> e MCP consomem), `operacao` (telemetria) e `uso` (quem usou). Junto: um `.sql`
> por tabela, e `src/` organizado por estágio, com **uma trilha por fonte**:
>
> ```
> coleta/ingresse.py -> cru.ingresse -> tratamento/ingresse.py -> tratado.eventos
>                                    -> curado (revisão humana) -> public -> site/MCP
> ```
>
> **Por quê:** hoje as camadas convivem no schema `public` e a fronteira entre
> elas é convenção verbal, não estrutura. A consequência é medida, não teórica:
> `store.upsert_eventos` escreve na bronze e na prata no mesmo comando; o passo
> "descrever" grava direto na tabela servida; e uma coluna da tabela servida
> (`categoria`) é destruída a cada rodada por outra escrita legítima — 197 dos
> 224 eventos do Sympla estão errados agora (§6.2). Sem fronteira física,
> "idempotente" é uma promessa que nada obriga a cumprir.
>
> **Absorve o NI-55** (`eventos` não é reconstruível a partir da bronze). Aqui
> ele deixa de ser item de backlog e vira a definição da camada `tratado`: se a
> prata não se reconstrói do cru, ela não é prata.

---

## 1. O que foi medido (2026-07-28, base de produção)

Números apurados antes de desenhar. Não são estimativas.

| Fato | Número |
|---|---|
| Eventos das 5 plataformas | 379 (+76 do Instagram = 455) |
| Eventos **sem** payload de catálogo na bronze | **0** |
| Payloads órfãos (bronze sem evento) | **0** |
| Eventos que perderiam a descrição numa reconstrução do zero | **0** |
| `eventos.raspado_em` ≠ `eventos_raw.raspado_em` | **0** de 379 |
| Re-normalização a partir da bronze: ids que mudariam | **0** de 379 |
| Re-normalização: campos divergentes | só `categoria` (197) e `url`/`endereco` do TnG (5) |

Volume (o que decide a retenção da §3.5):

| Tabela | Linhas | Em disco | Payload médio |
|---|---|---|---|
| `eventos` | 457 | 9,5 MB | — |
| `eventos_raw` | 875 | 3,9 MB | catálogo 3,3 KB · detalhe 17 KB · tickets 5,8 KB |
| `instagram_raw` | 271 | 1,9 MB | post 24 KB · story 12 KB · extração 416 B |
| `cinema_raw` | 64 | 656 KB | 20 KB |
| `cinema_extra_raw` | 78 | 160 KB | — |
| **banco `eventos`** | — | **25 MB** | — |
| **branch inteira** (o que o Neon limita) | — | **64,2 MB** | 12,5% do teto de 512 MiB |

⚠️ **O teto do Neon é por _branch_, não por banco** (conferido em 28/07). A
branch `production` carrega quatro bancos — `eventos` (25 MB), `eventos_teste`
(9,1 MB), `postgres` (7,9 MB) e `neondb` (7,5 MB, criado pelo Neon e nunca
usado) —, e é a soma deles que conta contra os 512 MiB. Todo cálculo de
orçamento nesta spec usa esse denominador. `neondb` é gordura removível de
graça; `eventos_teste` incha porque cada rodada de teste recria o schema.

**A conclusão que importa:** a camada prata **já é** reconstruível hoje, na
prática — o dado está todo lá. O que não existe é o *caminho de código* que faz
a reconstrução, e a *estrutura* que impede o caminho de escrita de burlá-la.

---

## 2. Os schemas

### 2.1 O mapa

| Schema | Papel | Tabelas | Quem escreve | Política |
|---|---|---|---|---|
| `cru` | Bronze — o que a fonte disse, **uma tabela por fonte** | `sympla`, `ingresse`, `shotgun`, `zig`, `ticketandgo`, `instagram`, `cinema`, `tmdb` | **só a coleta** | **nunca se dropa** |
| `tratado` | Prata — unificado, derivado, enriquecido | `eventos`, `lotes`, `filmes`, `sessoes` | **só o tratamento** | descartável: reconstrói-se |
| `curado` | O que uma **pessoa** decidiu | `correcoes`, `locais`, `pendencias` (view) | **só gente** (via ferramenta) | **nunca se dropa** |
| `public` | Ouro — contrato de consumo do site e do MCP | só views (§5) | ninguém | descartável |
| `operacao` | Telemetria do pipeline e artefatos nossos | `execucoes`, `coletas` (nova), `midias` | pipeline e coleta | **nunca se dropa** |
| `uso` | Quem usou — **dado de pessoa** | `usuarios`, `acessos` | MCP | **nunca se dropa**; LGPD |

**O schema comunica a política de recuperação**, que hoje vive como três
alíneas no CLAUDE.md que ninguém consegue aplicar sob pressão. A regra nova cabe
numa linha: **`cru`, `curado`, `operacao` e `uso` nunca se dropam; `tratado` e
`public` sempre se reconstroem.** Foi a falta disso que custou o catálogo do
Shotgun no drop de 27/07.

O critério é sempre o mesmo: **o que não se pode refazer sozinho não se dropa.**
`cru` porque a fonte não devolve o passado; `curado` porque é trabalho humano;
`operacao`/`uso` porque registram o que aconteceu uma vez.

### 2.2 A unificação acontece na prata, não na bronze

O `cru` guarda cada fonte no formato dela; `tratado.eventos` é onde as cinco (e
o Instagram) viram um schema só. Isso inverte o que existe hoje, em que
`eventos_raw` mistura cinco formatos numa tabela com uma coluna `payload` de
texto e a unificação acontece **antes** de gravar — no `_normalizar` de cada
scraper, em tempo de coleta.

`lotes`, `filmes` e `sessoes` seguem unificados: são derivadas de `tratado`, não
espelhos de fonte.

### 2.3 Por que `lotes` sai de `public`

`lotes` é 100% derivada do `cru` — `derivar.py` já a apaga e reinsere inteira a
cada rodada. É prata por definição. Ela é lida pelo `detalhar_evento` (e
portanto pelo site), mas o consumo atravessa a fronteira por uma view. **Ser
consumida não define a camada; ser reconstruível define.**

### 2.4 Qualificação explícita, sem `search_path` esperto

Todo SQL passa a nomear o schema: `cru.sympla`, `tratado.eventos`,
`public.eventos`. A alternativa (`SET search_path` e deixar o SQL como está)
economiza diff e cria uma armadilha: com uma view `public.eventos` e uma tabela
`tratado.eventos`, um `FROM eventos` depende da ordem do path — e o dia em que
alguém a alterar, metade do sistema muda de fonte de dados em silêncio.

---

## 3. O `cru`: uma tabela por fonte, append-only

### 3.1 O que a separação por fonte resolve

Não é só arrumação. Ela **resolve por estrutura três problemas que eu estava
resolvendo por código**:

1. **Os rótulos externos ao payload deixam de ser um problema.** O Shotgun e o
   Ticket and Go recebem `cidade_label`/`estado_label` de fora do payload
   (`shotgun.py:83`, `ticketandgo.py:208`), e o slug do Shotgun só existe na
   chave. Era o ponto de atenção nº 1 do NI-55, e a solução era reconstituir
   tudo por convenção ("o recorte é Brasília, então…"). Com tabela por fonte,
   **viram colunas**: `cru.shotgun.slug`, `cru.shotgun.cidade_label`. O dado que
   a coleta conhece fica gravado, não deduzido.
2. **A era do payload passa a ser declarada, não adivinhada.** Uma coluna `api`
   (`'v1'`/`'v2'`) preenchida pela coleta — que sabe qual endpoint chamou —
   torna a guarda da §6.3 uma comparação em vez de uma heurística sobre a forma
   do JSON. Não resolve retroativamente os 5 payloads V1 já gravados (esses
   entram como `api = NULL`, que é a informação honesta: "não sabemos"), mas
   fecha o problema para todas as trocas de API futuras.
3. **A retenção pode ser por fonte.** O Sympla muda o `global_score` todo dia e
   o Shotgun quase não muda; hoje os dois pagam a mesma política porque dividem
   a tabela.

Ganha-se ainda o óbvio: quando uma fonte morre, é **uma tabela e um script** —
dá para arquivar sem tocar no resto.

### 3.2 O formato comum

Todas as tabelas de `cru` compartilham o mesmo esqueleto:

```sql
-- sql/cru/sympla.sql
CREATE TABLE IF NOT EXISTS cru.sympla (
    id_nativo  TEXT NOT NULL,   -- id na fonte, SEM o prefixo "sympla:" (redundante aqui)
    origem     TEXT NOT NULL,   -- 'catalogo' | 'detalhe' | 'tickets'
    raspado_em TEXT NOT NULL,   -- ISO UTC: quando ESTA versão foi coletada
    hash       TEXT NOT NULL,   -- sha256 da forma canônica do payload
    payload    TEXT NOT NULL,   -- JSON como veio (fiel, não canonizado)
    api        TEXT,            -- era do endpoint; NULL = anterior ao registro
    PRIMARY KEY (id_nativo, origem, raspado_em)
);
```

E cada uma acrescenta o que só ela tem:

| Tabela | Colunas próprias | Origens |
|---|---|---|
| `cru.sympla` | — | `catalogo`, `detalhe`, `tickets` |
| `cru.ingresse` | `slug` | `catalogo`, `detalhe`, `tickets` |
| `cru.zig` | `slug` | `catalogo`, `detalhe`, `tickets` |
| `cru.shotgun` | `slug`, `cidade_label`, `estado_label` | `catalogo` (o JSON-LD traz tudo) |
| `cru.ticketandgo` | `slug`, `cidade_label`, `estado_label` | `catalogo`, `tickets` |
| `cru.instagram` | `perfil`, `code` (a chave é `code`, não `id_nativo`) | `post`, `story`, `extracao` |
| `cru.cinema` | `cinema_id`, `dia` (a chave é o par) | — |
| `cru.tmdb` | `filme_id` | — |

`instagram` e `cinema` **já são** tabelas por fonte hoje: a mudança regulariza o
que já era exceção. `eventos_raw` era o caso especial que misturava cinco.

> **O que NÃO fica no `cru`:** as URLs do pôster e do flyer no *nosso* storage
> (Vercel Blob). Não são payload de fonte — são artefato produzido por nós, e
> `cru` significa "o que a fonte disse". Vão para **`operacao.midias`**
> (`chave`, `url`, `subido_em`), que tem a mesma política de recuperação (não se
> refaz de graça: re-subir custa download + upload). Hoje vivem espalhadas entre
> `cinema_extra_raw` (origem `poster`) e `instagram_raw` (origem `midia`).

### 3.3 Append-only

**Decisão D1:** a bronze deixa de sobrescrever. Cada coleta que traz um payload
diferente do último **acrescenta uma versão**; nada é apagado no lugar. Isso
habilita histórico de preço ("esse lote subiu?" — dado de produto, não só
auditoria), rastro de mudança na fonte e reconstrução da prata **para qualquer
data passada**.

`hash` é `sha256` de `json.dumps(payload, sort_keys=True, ensure_ascii=False)`.
A canonização entra **só no hash**: o payload gravado é o que a fonte mandou.
Sem `sort_keys`, uma fonte que reordena chaves geraria versão nova a cada rodada
sem ter mudado nada.

```sql
INSERT INTO cru.sympla (id_nativo, origem, raspado_em, hash, payload, api)
SELECT %(id)s, %(origem)s, %(ts)s, %(hash)s, %(payload)s, %(api)s
WHERE (SELECT hash FROM cru.sympla
       WHERE id_nativo = %(id)s AND origem = %(origem)s
       ORDER BY raspado_em DESC LIMIT 1) IS DISTINCT FROM %(hash)s;
```

A comparação é com a **última** versão, não com "existe alguma igual": um
payload que vai de A para B e volta para A registra as três transições — o
comportamento certo para um lote que esgotou e voltou a ter estoque.

### 3.4 O tratamento lê uma view por fonte

```sql
-- sql/cru/sympla_atual.sql
CREATE OR REPLACE VIEW cru.sympla_atual AS
SELECT DISTINCT ON (id_nativo, origem) *
FROM cru.sympla ORDER BY id_nativo, origem, raspado_em DESC;
```

Cada `tratamento/<fonte>.py` consome a view `_atual` da sua fonte. Quem quiser
série temporal vai na tabela.

Para o relatório (hoje um `GROUP BY fonte, origem` numa tabela só), uma view de
inventário reúne as **contagens** das fontes — não os payloads:

```sql
-- sql/cru/inventario.sql
CREATE OR REPLACE VIEW cru.inventario AS
SELECT 'sympla' AS fonte, origem, count(*) AS versoes,
       count(DISTINCT id_nativo) AS registros, max(raspado_em) AS ultima
FROM cru.sympla GROUP BY origem
UNION ALL SELECT 'ingresse', origem, count(*), count(DISTINCT id_nativo), max(raspado_em)
FROM cru.ingresse GROUP BY origem
-- … uma linha por fonte
```

### 3.5 Retenção: janela de 90 dias

O dedupe por hash **não segura o crescimento tanto quanto parece**:

- **catálogo** (381 × 3,3 KB): o payload do Sympla carrega `global_score`, um
  score de trending que **muda todo dia**. Versão nova quase toda rodada.
- **tickets** (272 × 5,8 KB): `currentAvailableQty` muda a cada ingresso
  vendido. Versão nova toda rodada — e aqui a mudança é o que se quer guardar.
- **detalhe** (222 × 17 KB): coletado uma vez por evento. Desprezível.

Ou seja: **~2,7 MB por rodada diária, ≈ 1 GB/ano** sem poda.

**Decidido: janela de 90 dias.** Mantêm-se todas as versões dos últimos 90
dias; mais antigo que isso, sobra só a última versão de cada
`(id_nativo, origem)`. As tabelas de bruto estabilizam em **~250 MB**, no lugar
dos ~6,6 MB de hoje.

O denominador correto é a **branch**, não o banco `eventos` (§1): 64,2 MB hoje,
menos os 6,6 MB de bruto atual, mais 250 MB → **~308 MB, ou ~60% do teto de
512 MiB**. A conclusão de que cabe se mantém, mas com menos folga do que uma
conta sobre o banco isolado sugeriria — e o teto do Neon não é aviso, é a branch
virando somente-leitura.

A constante `JANELA_HISTORICO_DIAS` fica no código com esse número no comentário;
**30 dias ≈ 80 MB (~27% da branch) é o degrau se apertar**, e apertar é uma
mudança de constante, não de desenho. Duas folgas baratas antes de mexer nela:
dropar o `neondb` (7,5 MB, nunca usado) e reclamar o inchaço do `eventos_teste`.
**É a única exceção ao "nada é apagado"**, e poda só versões intermediárias
antigas, nunca o estado atual.

A poda roda por fonte (§3.1, item 3), com a mesma consulta parametrizada pelo
nome da tabela — que vem de uma **allowlist em código**, nunca de string
concatenada.

### 3.6 Onde a política difere, e por quê

Append-only vale onde o dado **muda e a mudança tem valor**:

- **`cru.cinema`** — snapshot com poda de dias passados, por decisão explícita
  da spec 20260711_raspagem-cinema: a grade da semana passada não tem consulta
  que a justifique. Histórico custaria 20 KB × 64 por rodada para responder
  pergunta que ninguém faz.
- **`cru.instagram`** — o post não muda depois de publicado; a extração do
  flyer é incremental por design. Último-vence já é imutável na prática.
- **`cru.tmdb`** e **`operacao.midias`** — incrementais: só se busca o que ainda
  não tem.

Cada `.sql` documenta a política da sua tabela no cabeçalho, para a diferença
ser escolha lida e não inconsistência herdada.

---

## 4. A camada `curado` — o que uma pessoa decidiu

O tratamento é automático e reescreve tudo. Por isso, **qualquer correção
humana feita dentro de `tratado` é apagada na próxima rodada** — é o que
acontece hoje se alguém consertar um nome no DBeaver. `curado` existe para que
a decisão humana viva **fora** do que se reconstrói, e seja **reaplicada** como
o último passo do tratamento.

### 4.1 `curado.correcoes` — override sobre um registro tratado

```sql
CREATE TABLE IF NOT EXISTS curado.correcoes (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entidade      TEXT  NOT NULL,   -- 'eventos' | 'filmes' | ...
    registro_id   TEXT  NOT NULL,   -- tratado.<entidade>.id
    valores       JSONB NOT NULL,   -- só o que muda: {"nome": "...", "ruido": 1}
    valores_antes JSONB,            -- o que estava lá quando se corrigiu
    motivo        TEXT  NOT NULL,   -- POR QUÊ — obrigatório, não é comentário
    autor         TEXT  NOT NULL,
    criado_em     TEXT  NOT NULL,   -- ISO UTC
    revogada_em   TEXT              -- NULL = ativa; correção não se apaga
);
```

Decisões embutidas no formato:

- **`motivo` é `NOT NULL`.** A explicação do que mudou, quando e por quê não é
  metadado opcional — é o produto da curadoria. Correção sem motivo vira
  mistério em três meses.
- **Append-only, como o `cru`.** Revogar preenche `revogada_em`, nunca deleta:
  histórico de decisão humana é tão insubstituível quanto dado bruto.
- **`JSONB` em vez de coluna por campo.** Uma tabela serve todas as entidades, e
  caso novo não exige DDL novo. Quais campos são curáveis é uma **allowlist em
  código** (`nome`, `local_nome`, `categoria`, `ruido`, `cancelado`, …); `id`,
  `fonte` e `busca` nunca.
- **`valores_antes` detecta correção obsoleta.** Se o valor atual em `tratado`
  já não é o que era quando se corrigiu, a fonte provavelmente consertou
  sozinha — o relatório aponta "3 correções podem ter virado desnecessárias" em
  vez de mascarar dado bom para sempre.

Aplicação: `tratamento/curadoria.py` roda **depois do enriquecer e antes do
FTS** — depois porque a curadoria precisa poder derrubar uma decisão dele
(desfazer um dedupe errado); antes para a busca indexar o texto corrigido.

### 4.2 `curado.locais` — a referência canônica de casas

Hoje o conhecimento sobre locais está espalhado em três lugares que não se
falam: `dados/locais_df.yaml` (a lista que ancora o recorte DF do Ticket and
Go), os `local_aliases` da watchlist do Instagram (que canonizam "Culto" ↔
"Culto Rock Bar" no dedupe) e o `local_nome` cru de cada fonte.

```sql
CREATE TABLE IF NOT EXISTS curado.locais (
    id         TEXT PRIMARY KEY,   -- slug canônico: 'culto-rock-bar'
    nome       TEXT NOT NULL,      -- nome canônico de exibição
    aliases    TEXT[] NOT NULL DEFAULT '{}',  -- como as fontes escrevem
    no_df      BOOLEAN NOT NULL DEFAULT TRUE, -- ancora o recorte do TnG
    instagram  TEXT,               -- @ do perfil, quando há
    observacao TEXT,
    autor      TEXT NOT NULL,
    criado_em  TEXT NOT NULL,
    atualizado_em TEXT
);
```

É **referência**, não override: consumida pelo tratamento (dedupe, conciliação
Instagram ↔ plataforma) e pela coleta (o filtro `_do_df` do Ticket and Go).

### 4.3 O que **não** migra para `curado`

A distinção que mantém a camada honesta: **`curado` guarda decisão sobre dado
que já entrou; YAML versionado guarda configuração do que se vai coletar.**

`dados/perfis_instagram.yaml` (a watchlist) é configuração de entrada — muda o
que se raspa, não corrige o que se raspou. Continua em YAML, versionada, com
revisão por PR e histórico no git, como o CLAUDE.md determina. O mesmo vale
para os termos de ruído do `enriquecer.py` e `docs/backlogs/rejeitado.yaml`.

`dados/locais_df.yaml` migra: é referência sobre entidades do mundo, consultada
em execução por dois estágios, e cresce por curadoria contínua.

### 4.4 Como se faz a curadoria (a ferramenta)

**`curado.pendencias`** — a fila: o que precisa de olho humano e que hoje se
perde no stdout do relatório. Três dos quatro sinais são **calculáveis por
`JOIN`**, então a view não depende de o tratamento ter lembrado de registrar
nada — ela está sempre atual, e não há tabela nova para manter:

| Sinal | Como sai |
|---|---|
| Payload que o tratamento não conseguiu ler (§6.3) | registro em `cru.<fonte>_atual` **sem** linha correspondente em `tratado.eventos` |
| Local fora da referência canônica | `tratado.eventos.local_nome` que não casa com nenhum `curado.locais.aliases` — é o "candidato a `locais_df.yaml`" que o Ticket and Go imprime e o terminal engole |
| Correção órfã ou obsoleta | `curado.correcoes` ativa cujo `registro_id` sumiu, ou cujo `valores_antes` não bate mais com `tratado` (§4.1) |
| Dedupe de similaridade limítrofe | **o único que exige persistir algo**: o `enriquecer` calcula o score de similaridade e o descarta. Precisa gravá-lo em `tratado.eventos.dedupe_score` (coluna nova, aditiva) para a view poder filtrar a faixa cinzenta |

**`src/ferramentas/curar.py`** — a CLI mínima: listar pendências, aplicar
correção com motivo obrigatório, revogar, listar ativas. Sem interface gráfica
nesta spec.

A evolução natural — e provavelmente o fim lógico num produto que **é** um
agente — é curar conversando: uma tool MCP de escrita. Fica fora do escopo
porque muda o modelo de segurança do MCP remoto, hoje somente-leitura.

---

## 5. `public` como contrato de consumo

**Decisão D3:** `public` não tem tabela, só views sobre `tratado`.

```sql
-- sql/public/eventos.sql
CREATE OR REPLACE VIEW public.eventos AS
SELECT id, fonte, id_nativo, nome, start_date, end_date, cidade, estado,
       local_nome, endereco, bairro, lat, lon, categoria, organizador, url,
       imagem, descricao, atracoes, preco_min, tem_gratis, esgotado,
       popularidade, cancelado, sumido, ruido, dedupe_grupo, dedupe_canonico,
       busca
FROM tratado.eventos;
```

O ganho não é esconder linha — é **desacoplar o formato consumido do formato
armazenado**. Hoje uma mudança de coluna em `eventos` quebra ao mesmo tempo a
derivação, a consulta, o MCP e o site. Com a view no meio, `tratado` pode mudar
e a view absorve.

**O que a view deliberadamente NÃO faz:** filtrar ruído/cancelado/sumido — essa
decisão é da consulta, que precisa poder mostrar os dois lados
(`incluir_ruido=True` existe e serve para depurar). Filtro de linha em view é
regra de negócio escondida.

**Nem esconder `organizador`:** a omissão é postura de *canal* (página pública
indexável vs. MCP em contexto privado) e continua em `api/dados.py`.

---

## 6. O que a fronteira física conserta (achados desta investigação)

### 6.1 A coleta escreve na prata — e por isso a prata não é reconstruível

`store.upsert_eventos` (`src/store.py:80`) grava em `eventos` **e** em
`eventos_raw` no mesmo comando. `_descrever` (`src/atualizar.py:230`) faz
`UPDATE eventos SET descricao, categoria` direto. O Shotgun grava `preco_min` na
prata pelo próprio `_normalizar`. **Não existe uma linha de código que leia
`eventos_raw` e produza `eventos`** — a bronze é arquivo morto, porque a escrita
da prata sempre veio de graça junto da coleta.

Para saber por que um evento está do jeito que está, é preciso conhecer a
história de todas as rodadas que passaram por ele. Não dá para olhar o cru e
dizer o que a prata deveria conter.

Na estrutura nova isso é uma violação de camada que o schema torna visível:
**a coleta nunca escreve em `tratado`** (§12-D2).

### 6.2 Bug vivo: a categoria do Sympla é destruída a cada rodada

**206 dos 224 eventos do Sympla têm `categoria = 'NORMAL'`** enquanto o payload
de detalhe já guardado diz `'musica'` (167), `'gastronomia-comidas-e-bebidas'`,
`'sociedade-e-cultura'` e mais 14 valores reais. Três regras corretas
isoladamente se combinam mal:

1. o passo "descrever" grava a categoria boa, vinda do BFF de página;
2. o `upsert_eventos` **não** protege `categoria` (`src/store.py:77`), então a
   próxima raspagem do catálogo a sobrescreve com o `event_type`;
3. o "descrever" é incremental (`WHERE descricao IS NULL`) e **nunca volta**.

Só os 18 eventos descritos depois da última raspagem do catálogo estão certos.
Isso polui o FTS, que indexa `categoria`.

Ninguém escreveu esse comportamento: ele emergiu de duas escritas disputando a
mesma coluna, onde **quem escreve por último ganha**.

**`catalogo.event_type` não é categoria — é `'NORMAL'` nos 224 eventos, sem
exceção.** É um flag de modalidade (presencial/online) com **zero** poder de
distinção, mapeado para `categoria` por engano no `_normalizar`. Isso corrige a
precedência que esta spec anunciava (`detalhe.eventsCategory` >
`catalogo.event_type`): não há o que desempatar, o lado do catálogo é ruído puro
e sai de cena.

> ⚠️ **Correção ao rascunho anterior.** Ele prescrevia "`categoria` em
> `_COLS_PRESERVAR` (uma linha)" — e isso **não consertaria nada**:
> `_COLS_PRESERVAR` protege via `COALESCE(excluded.c, eventos.c)`, que só age
> quando o valor novo é `NULL`. `'NORMAL'` nunca é `NULL`, então sobrescreveria
> a categoria boa exatamente como hoje. O erro era supor que o catálogo às vezes
> não mandava categoria; ele sempre manda, e sempre a mesma.

Estanca-sangue correto (fatia 1), três passos e nenhuma requisição de rede:

1. `sympla._normalizar` para de mapear `event_type` → `categoria` (vira `None`);
2. `categoria` entra em `_COLS_PRESERVAR` — agora com efeito, porque o valor
   novo passa a ser `NULL` e o `COALESCE` preserva o que o "descrever" colheu;
3. reposição única dos 206 a partir do `eventos_raw`.

Com a fronteira física o bug não tem como existir: as duas escritas viram
gravações no `cru`, e `tratamento/sympla.py` lê a categoria de um lugar só.

### 6.3 A bronze tem *eras*, e o tratamento precisa saber disso

5 dos 85 payloads de catálogo do Ticket and Go são da **API V1**, desligada em
28/07 — schema completamente diferente (`slug`, `endereco_completo`,
`latitude`). O parser atual aplicado a eles **não falha**: acha `nome`,
`inicio` e `hora_incio` por coincidência de nomes de campo e degrada em
silêncio, perdendo o endereço e montando `.../evento/` sem slug.

Vale para todo o futuro: cada troca de API deixa duas eras de payload sob a
mesma origem. Aconteceu duas vezes em 20 dias.

- **A coluna `api`** (§3.1) resolve para a frente: a coleta declara a era.
- **Guarda genérica**, para qualquer fonte e para o passado (`api IS NULL`): o
  tratamento só escreve se o resultado tiver `nome` e `url` não-nulos **e** o id
  bater com a chave da bronze. Payload não reconhecido é **pulado e vira
  pendência de curadoria** (§4.4) — nunca sobrescreve dado bom com lixo
  plausível.
- **Tolerância por fonte**, onde valer: em `tratamento/ticketandgo.py`, três
  expressões `or` (`slug_evento or slug`, `endereco_completo`,
  `latitude/longitude`) recuperam os 5 e zeram a divergência.

### 6.4 Desperdício: o "descrever" re-busca eternamente quem não tem descrição

O passo seleciona `WHERE descricao IS NULL`. O Sympla tem 215 payloads de
detalhe para 204 descrições: **11 eventos cujo detalhe existe mas veio sem
texto são re-buscados em toda rodada, para sempre.** Com a bronze como fonte da
verdade do que já foi coletado, o critério correto é "não existe payload
`detalhe` em `cru.sympla` para este id".

### 6.5 `raspado_em` é carimbado com `now()` dentro do `_normalizar`

Os cinco scrapers fazem `"raspado_em": datetime.now(timezone.utc).isoformat()`
dentro da normalização (ex.: `src/scrapers/sympla.py:145`). Como ela passa a
rodar no tratamento, isso reescreveria a âncora do `sumido` com a hora do
tratamento. **O timestamp vem do `cru`**, que é o momento real da coleta — e que
hoje bate com `eventos.raspado_em` em 379/379.

### 6.6 O import do `shotgun.py` arrasta o Playwright

`from playwright.sync_api import sync_playwright` está no topo do módulo
(`src/scrapers/shotgun.py:28`). Importar o normalizador puxa uma dependência de
navegador — o CI parou de instalar o Chromium em 28/07 justamente para
emagrecer. Com a separação em `coleta/shotgun.py` e `tratamento/shotgun.py`, o
problema desaparece por construção: só o primeiro conhece Playwright.

### 6.7 Dívida consciente: o recorte roda na coleta, não no tratamento

Todos os filtros de escopo rodam hoje **antes** de gravar no cru: `themes=99` do
Sympla, `state == "DF"` do Zig, `_do_df` do Ticket and Go, `apenas_futuros` de
todos. O medalhão puro diria o contrário — o cru guarda o que a fonte deu; o
recorte é decisão, e decisão pertence ao tratamento.

O custo diz o contrário: o catálogo nacional do Ticket and Go tem ~430 futuros
contra os ~85 do DF, e guardar todos custaria ~2 MB por rodada — que com a
janela de 90 dias vira ~190 MB só dessa fonte, quase dobrando a base projetada.

**Fica na coleta**, conscientemente. Consequência aceita: mudar a regra de
recorte (ex.: incluir uma casa nova em `curado.locais`) **não** recupera eventos
passados a seco — exige re-raspar. Mitigação: a raspagem do TnG leva ~3 min,
então "mudou a lista, roda o TnG" é procedimento barato, registrado no cabeçalho
de `curado.locais`.

---

## 7. Organização dos arquivos

### 7.1 `sql/` — um arquivo por tabela

```
sql/
  00_extensoes.sql          -- unaccent + a configuração de busca 'pt'
  01_schemas.sql            -- CREATE SCHEMA IF NOT EXISTS cru, tratado, curado, operacao, uso
  cru/
    sympla.sql  ingresse.sql  shotgun.sql  zig.sql  ticketandgo.sql
    instagram.sql  cinema.sql  tmdb.sql
    _atual.sql              -- as views DISTINCT ON, uma por fonte
    inventario.sql
  tratado/
    eventos.sql   lotes.sql   filmes.sql   sessoes.sql
  curado/
    correcoes.sql   locais.sql   pendencias.sql
  operacao/
    execucoes.sql   coletas.sql   midias.sql
  uso/
    usuarios.sql   acessos.sql
  public/
    eventos.sql   lotes.sql   filmes.sql   sessoes.sql        -- views
  manutencao/
    reconstruir_fts.sql   podar_historico.sql
```

Regras:

- **ordem fixa em código**: `00_`/`01_` → `cru/` → `tratado/` → `curado/` →
  `operacao/` → `uso/` → `public/` (views por último); dentro de cada pasta,
  ordem alfabética. Nada de numerar arquivo.
- **idempotente**: `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` /
  `CREATE OR REPLACE VIEW`. Não é migração versionada (§12-D7).
- **concatenados num único `execute`**: ~28 arquivos × 1 RTT ao Neon por
  conexão seria desperdício, e o pipeline abre várias conexões curtas.
- `conectar()` ganha `aplicar_schema=False` por padrão: só entrypoints de
  escrita e testes aplicam DDL (§12-D8).

### 7.2 `src/` — por estágio, com uma trilha por fonte

```
src/
  base/            # infra transversal, sem regra de negócio
    conexao.py     #   (ex-store: conectar, env_var, aplicar DDL)
    tempo.py
  coleta/          # ESTÁGIO 1 — rede; NUNCA escreve em `tratado`
    sympla.py  ingresse.py  shotgun.py  zig.py  ticketandgo.py
    instagram.py  cinema.py  tmdb.py  midias.py
    gravar.py      #   o append-only com dedupe por hash (§3.3), comum a todas
  tratamento/      # ESTÁGIO 2 — a seco; lê `cru` + `curado`, escreve `tratado`
    sympla.py  ingresse.py  shotgun.py  zig.py  ticketandgo.py
    instagram.py  cinema.py
    comum.py       #   guardas, upsert em tratado.eventos, agregação de lotes
    enriquecer.py  #   ruído + dedupe (cross-fonte, roda depois de todas)
    curadoria.py   #   aplica curado.correcoes; alimenta curado.pendencias
    sumido.py      #   deriva de operacao.coletas
    busca.py       #   FTS
  servico/         # ESTÁGIO 3 — lê `public`
    consulta.py  mcp_server.py  auth.py
  pipeline/
    atualizar.py   #   orquestra os estágios
  ferramentas/
    curar.py  discover_sympla.py  exportar.py (NI-56)
```

**A trilha de uma fonte cabe em dois arquivos**, e é isso que a mudança compra:
`coleta/sympla.py` sabe **falar** com o Sympla (endpoints, paginação, pausas) e
`tratamento/sympla.py` sabe **ler** o Sympla (payload → schema unificado, lotes,
colunas derivadas).

Hoje esse conhecimento está partido em três lugares que ninguém lembra que se
relacionam: `scrapers/sympla.py` (rede + normalização do catálogo),
`derivar.py::_sympla_catalogo`/`_sympla_detalhe` (colunas derivadas) e
`derivar.py::_lotes_sympla` (lotes). **`derivar.py` se dissolve**: cada pedaço
volta para a fonte que ele entende, e o que sobra (`_agregar`, o upsert, as
guardas) vira `tratamento/comum.py`.

O risco da separação é o esqueleto duplicar sete vezes e as cópias divergirem
por descuido. `comum.py` é a resposta: cada `tratamento/<fonte>.py` declara
**só o mapeamento** e chama o mesmo motor.

**Imports:** cada entrypoint insere `src/` no `sys.path` (padrão que `api/` e
`tests/` já usam) e os módulos importam por pacote: `from base import conexao`,
`from tratamento import comum`. Subpastas funcionam como namespace packages, sem
`__init__.py`, como `scrapers/` já funciona hoje.

**`store.py` deixa de existir** como catch-all: hoje acumula conexão, DDL,
upsert da prata, gravação da bronze e registro de execução — quatro estágios no
mesmo arquivo.

---

## 8. O pipeline reescrito

```
COLETA (rede)                             -> escreve em cru/ e operacao/, nunca em tratado/
  coleta/sympla.py       catálogo, detalhe, tickets  -> cru.sympla
  coleta/ingresse.py                                 -> cru.ingresse
  coleta/zig.py                                      -> cru.zig
  coleta/shotgun.py                                  -> cru.shotgun
  coleta/ticketandgo.py                              -> cru.ticketandgo
  coleta/cinema.py                                   -> cru.cinema
  coleta/instagram.py    posts, stories, extração    -> cru.instagram
  coleta/tmdb.py                                     -> cru.tmdb
  coleta/midias.py       pôster e flyer no Blob      -> operacao.midias
  toda coleta registra início/resultado              -> operacao.coletas

TRATAMENTO (a seco)                       -> reescreve tratado/ do zero
  tratamento/<fonte>.py  cru.<fonte>_atual -> tratado.eventos + tratado.lotes
  tratamento/cinema.py   cru.cinema+tmdb   -> tratado.filmes, tratado.sessoes
  tratamento/sumido.py   operacao.coletas  -> tratado.eventos.sumido
  tratamento/enriquecer.py  ruído + dedupe -> tratado.eventos   (cross-fonte)
  tratamento/curadoria.py   curado.*       -> tratado.*         (override humano)
  tratamento/busca.py       FTS            -> tratado.*.busca

SERVIÇO
  servico/consulta.py -> public.*  <- mcp_server.py, api/dados.py
```

**A regra que o desenho inteiro serve:** tudo que tem rede é coleta; tudo que é
a seco é tratamento, e **só o tratamento escreve em `tratado`**. Sem exceção —
nem para o "descrever", nem para o `preco_min` do Shotgun.

A regra é essa, e não "a coleta só escreve em `cru`": a coleta também escreve em
`operacao` (o registro da própria coleta, e as mídias que ela sobe). O que a
torna disciplinada não é escrever num único schema — é **nunca tocar na camada
servida**.

### 8.1 O tratamento roda em UMA transação, com `DELETE` e não `TRUNCATE`

Consequência de `public` ler `tratado`: enquanto o tratamento reconstrói, o site
e o MCP continuam consultando. Duas exigências, e as duas são de implementação,
não de gosto:

- **Uma transação para o ciclo inteiro.** Sem isso, existe uma janela de
  segundos em que `tratado.eventos` está vazia e o site serve "nenhum evento
  encontrado". Hoje isso não morde porque a reconstrução é parcial e rápida; com
  a prata inteira sendo reescrita, morderia.
- **`DELETE`, não `TRUNCATE`.** No Postgres o `TRUNCATE` é transacional, mas
  toma `ACCESS EXCLUSIVE` — os leitores **bloqueiam** até o commit, em vez de
  enxergar a versão anterior. Com `DELETE`, o MVCC deixa o site lendo o estado
  antigo até o instante do commit, sem esperar. A diferença é invisível em
  desenvolvimento e visível em produção.

**Ordem dentro do tratamento importa em dois pontos, e só neles:** o enriquecer
roda depois de todas as fontes (o dedupe é cross-fonte, e é ele que concilia
Instagram ↔ plataforma); a curadoria roda depois do enriquecer e antes do FTS
(§4.1). Os sete tratamentos de fonte, entre si, são independentes.

**`sumido` vira derivável.** Testei a regra ingênua (evento futuro cujo
`raspado_em` ficou atrás do último da fonte): bate em só **43 de 381**, porque o
`raspado_em` varia dentro da mesma rodada, evento a evento. A âncora correta é o
*início da coleta daquela fonte* — que hoje só existe como variável local do
`atualizar.py`. Registrada em `operacao.coletas` (uma linha por fonte por
rodada, com `iniciada_em`, `coletados` e erro), `sumido` vira derivação a seco, e
a guarda do NI-59 (coleta zerada não marca sumido) vira um `WHERE coletados > 0`
em vez de um `if` no meio da orquestração.

---

## 9. Migração

Inventário conferido na base de produção em 28/07: **um único schema (`public`),
11 tabelas, 2 sequences, nenhuma chave estrangeira, nenhuma coluna gerada,
25 MB.** A migração toca as 11 — e quatro delas não se refazem de jeito nenhum
(`eventos_raw`, `instagram_raw`, `cinema_raw`, `cinema_extra_raw`), mais
`execucoes`, `usuarios` e `acessos`.

### 9.1 Três redes, porque falham de jeitos diferentes

| Rede | O que cobre | O que **não** cobre | Custo |
|---|---|---|---|
| **`pg_dump` num arquivo datado, fora do Neon** | o Neon fora do ar, conta perdida, erro descoberto semanas depois | consulta lado a lado; restaurar é operação manual | segundos |
| **Branch do Neon, criado antes do primeiro comando** | erro na própria migração, **inclusive o que esta spec não previu** (objeto esquecido, permissão, extensão) | qualquer coisa se ele **não** tiver sido criado antes — ver §9.1.1 | copy-on-write: instantâneo |
| **Schema `legado_AAAAMMDD` no mesmo banco** | a janela de observação — é o único que permite `JOIN` entre o dado velho e o novo | um desastre no banco inteiro | ~25 MB |

Uma só não basta porque cada uma falha num eixo diferente: o dump é forte e
inerte, o branch é abrangente e local, o schema é frágil e **consultável** — e é
a consultabilidade que sustenta a janela de validação da §9.9.

### 9.1.1 O passado dura SEIS HORAS neste plano

Conferido na conta em 28/07 (`neonctl`), plano **free**, projeto `ZeroUm`
(`shiny-forest-94210371`), região `sa-east-1`, **Postgres 18**:

| | |
|---|---|
| `history_retention_seconds` | **21600 — 6 horas** |
| `branch_logical_size_limit` | 512 MiB **por branch** |
| Branch em uso | uma só (`production`), 64,2 MB lógicos |
| Armazenamento sintético do projeto | 106,7 MB |

**Restauração no tempo (PITR) cobre 6 horas, não dias.** No dia seguinte à
migração não existe "voltar para antes" — o histórico já expirou. Isso inverte o
que esta spec supunha ao listar as redes: o branch **não é redundância do dump**,
é o único jeito de o estado pré-migração sobreviver à janela de observação de 2–3
dias da §9.9.

Um branch **criado de propósito** não expira: é objeto real, com dado próprio, e
fica até ser removido à mão. O que expira é a possibilidade de *criar* um a
partir de um ponto passado. Consequência direta no procedimento: **criar o branch
é passo obrigatório do §9.8-1, não precaução opcional** — e se for esquecido, seis
horas depois a omissão é irreversível.

> Como o `pg_dump` local roda com a versão 18.1 e o servidor é Postgres 18, não
> há incompatibilidade de versão entre dump e restauração.

`pg_dump` 18.1 já está instalado (`C:\Program Files\PostgreSQL\18\bin`):

```
pg_dump -Fc -f backups/eventos_20260728_pre-medalhao.dump "$EVENTOS_DB_URL"
```

`-Fc` (custom) e não CSV: preserva tipos, `NULL` vs. string vazia, `tsvector` e
a ordem de restauração. **O arquivo contém `usuarios`/`acessos` — dado de
pessoa.** Fica fora do repositório (ou em `backups/`, gitignorado), não sobe
para lugar nenhum e não vira anexo de nada.

> Isso **substitui a exportação em CSV do NI-56** como pré-requisito desta
> migração: o `pg_dump` faz o mesmo trabalho melhor e sem código nosso. Se o
> NI-56 sobrevive como rotina periódica é outra decisão, fora daqui.


### 9.2 Por que um schema datado, e não `cru.eventos_raw_legado`

O rascunho anterior protegia **uma** tabela — a que já tinha sido perdida uma
vez. A migração mexe em onze, e as outras dez tinham como rede só um CSV: outro
formato, outro lugar, outro caminho de restauração, exercitado nunca.

Pior: `cru.eventos_raw_legado` colocaria uma tabela morta **dentro do schema que
a §2.1 declara que nunca se dropa** — contradizendo a regra nova na primeira
oportunidade de aplicá-la, e deixando um resíduo que ninguém teria coragem de
remover depois.

Um schema de backup com **a data no nome** resolve os três de uma vez: cobre
tudo, tem a validade auto-documentada no próprio nome, e mora num lugar cujo
propósito inteiro é ser dropado.

### 9.3 Tudo vai para o legado primeiro; o novo se constrói a partir dele

A ordem é o contrário do intuitivo, e é ela que garante a fidelidade:

```sql
CREATE SCHEMA legado_20260728;
ALTER TABLE public.eventos SET SCHEMA legado_20260728;   -- … as 11
```

`SET SCHEMA` não copia dado, é instantâneo e **leva junto os índices e as
sequences de identidade**. O backup passa a ser o objeto original intacto, e não
uma reconstrução dele — qualquer coisa sutil que a cópia erre cai do lado
descartável, nunca do lado da rede de segurança. De quebra, `public` fica vazio,
o que elimina o impedimento óbvio: uma view `public.eventos` não pode nascer
enquanto existir uma tabela com esse nome.

O novo se constrói copiando **do legado**:

```sql
INSERT INTO tratado.eventos (<colunas>) SELECT <colunas> FROM legado_20260728.eventos;
```

> **As tabelas de destino são criadas pelos `.sql` de `sql/` (`store.ddl()`), e
> não por `LIKE ... INCLUDING ALL`** como o rascunho previa. Motivo descoberto
> ao implementar: `LIKE INCLUDING INDEXES` gera **nomes de índice novos**, e o
> `CREATE INDEX IF NOT EXISTS idx_eventos_start` do DDL criaria então um índice
> **duplicado** — o `IF NOT EXISTS` casa por nome, não por definição. Usar o DDL
> é seguro porque a fatia 2 provou que ele reproduz o schema de produção coluna
> a coluna, e de quebra torna os `.sql` a fonte única de verdade, que era o
> objetivo. As colunas são listadas explicitamente nos dois lados do `INSERT`,
> o que torna a cópia independente da ordem física.

Três armadilhas, todas conferidas contra a base real:

- **Chave estrangeira não sobrevive a cópia nenhuma** (nem `LIKE INCLUDING ALL`,
  nem `CREATE TABLE`). **Não há nenhuma FK neste banco**, por decisão registrada
  no próprio DDL ("sem FK para filmes… quem garante a consistência é a
  derivação"). Reconferir se alguma nascer.
- **`INSERT ... SELECT` FALHA em `execucoes` e `acessos`.** As duas têm
  `id BIGINT GENERATED ALWAYS AS IDENTITY`, que **recusa valor explícito**;
  precisa de `OVERRIDING SYSTEM VALUE`. São justamente duas das que não se
  reconstroem — e o erro aparece no meio da migração, não antes.
- **A sequence da tabela nova nasce em 1.** Com `execucoes` já tendo os ids 1–5,
  o **primeiro** `registrar_execucao()` depois da migração colidiria na PK. Some
  na mesma transação:
  ```sql
  SELECT setval(pg_get_serial_sequence('operacao.execucoes','id'),
                COALESCE((SELECT max(id) FROM operacao.execucoes), 0) + 1, false);
  ```
  Idem `uso.acessos` (hoje vazia, mas a linha é a mesma).

**Nenhuma coluna é gerada** (conferido), então `SELECT *` é seguro:
`eventos.busca` é `TSVECTOR` comum, preenchida pelo `reconstruir_fts` por
decisão explícita — `unaccent` não é `IMMUTABLE`.

### 9.4 As que se dividem, e a prova que substitui o palpite

- `eventos_raw` (875 linhas) → `cru.sympla` | `ingresse` | `shotgun` | `zig` |
  `ticketandgo`, cortando o prefixo do `evento_id` para virar `id_nativo`.
- `cinema_extra_raw` (78) → `cru.tmdb` (origem `tmdb`) + `operacao.midias`
  (origem `poster`); a origem `midia` de `instagram_raw` vai junto para
  `operacao.midias`.

O rascunho anterior discutia se o corte do prefixo devia ser `substring(evento_id
from position(':' in evento_id) + 1)` ou `split_part(...,':',2)`, argumentando
que o slug do Shotgun poderia conter `:`. **A pergunta certa não é qual usar — é
como provar que funcionou.** Três invariantes, e elas valem para qualquer forma
de cortar:

1. **Nada sem destino:** a soma das linhas das cinco tabelas novas = 875, e todo
   `evento_id` do legado casa com exatamente uma fonte conhecida.
2. **Ida e volta da chave:** `'<fonte>:' || id_nativo` reproduz o `evento_id`
   original, linha a linha.
   ```sql
   -- tem de devolver 0
   SELECT count(*) FROM cru.sympla c
    WHERE NOT EXISTS (SELECT 1 FROM legado_20260728.eventos_raw r
                       WHERE r.evento_id = 'sympla:' || c.id_nativo
                         AND r.origem = c.origem);
   ```
3. **Payload byte-idêntico:** `md5(payload)` casa por chave. O payload é o dado
   bruto; qualquer transformação nele é perda, não migração.

### 9.5 Contagem não prova conteúdo

Para toda tabela copiada, antes e depois, um par que precisa bater:

```sql
SELECT count(*) AS n, md5(string_agg(t::text, '' ORDER BY t::text)) AS h
FROM legado_20260728.eventos t;
```

A linha inteira como texto pega o que a contagem não pega: valor corrompido,
coluna trocada de ordem, coerção de tipo que mudou um número em silêncio. Com
875 linhas na maior tabela, o custo é irrelevante.

### 9.6 Uma transação, com as conferências DENTRO dela

DDL no Postgres é transacional: `CREATE SCHEMA`, `SET SCHEMA`, `CREATE TABLE`,
`INSERT` e `setval` desfazem num `ROLLBACK`. Então a migração é **uma
transação**, e as conferências das §9.4/§9.5 rodam dentro dela, abortando
sozinhas:

```sql
DO $$
DECLARE orfaos bigint;
BEGIN
    SELECT count(*) INTO orfaos FROM legado_20260728.eventos_raw r
     WHERE NOT EXISTS (…a linha correspondente em cru.*…);
    IF orfaos > 0 THEN
        RAISE EXCEPTION 'migração abortada: % payloads sem destino', orfaos;
    END IF;
END $$;
```

Conferir **depois** do commit também funciona — o legado está lá. Mas transforma
um `ROLLBACK` silencioso, que ninguém precisa saber que aconteceu, num incidente
com estado intermediário para desfazer à mão. Melhor que o errado nunca chegue a
existir.

### 9.7 O caminho de leitura não quebra — e isso não é sorte

`consulta.py` lê exatamente quatro relações: `eventos`, `lotes`, `filmes`,
`sessoes` (conferido). São exatamente os quatro nomes que a §5 recria como views
em `public`. **Site e MCP continuam servindo durante e depois da migração, sem
deploy nenhum**, porque a camada servida manteve os nomes. É a decisão D3 pagando
sozinha antes mesmo de ser exercida para o que foi criada.

Quem precisa de código novo é o caminho de **escrita** (`atualizar.py`) — que não
roda na Vercel.

### 9.8 Ordem de execução — e são DUAS janelas, não uma

O procedimento acima roda **duas vezes**, porque a migração se parte entre as
fatias da §13. Fingir que é um evento único seria a única forma de transformá-la
numa operação grande e irreversível:

| Janela | Fatia | O que faz | Risco |
|---|---|---|---|
| `legado_AAAAMMDD` #1 | 3 | criar os schemas, mover as 11 tabelas, criar as views | baixo: `SET SCHEMA` não move byte |
| `legado_AAAAMMDD` #2 | 5 | dividir `eventos_raw` em cinco + `cinema_extra_raw` em duas, com append-only | **é a que toca a tabela que já custou um catálogo** |

Cada janela leva as três redes completas. Em cada uma:

0. **Desligar o `schedule:` do cron** (`.github/workflows/raspar.yml`, 06:00 UTC)
   e confirmar que nenhuma rodada está em voo. O `workflow_dispatch` continua.
1. `pg_dump` **e** branch do Neon — os dois, e o branch **antes** de qualquer
   comando. Passada a janela de 6 h da §9.1.1, esquecer este passo é
   irreversível:
   ```
   neonctl branches create --project-id shiny-forest-94210371 \
     --name pre-medalhao-20260728
   ```
2. A transação da §9.6 — `CREATE SCHEMA legado_…` → os `SET SCHEMA` → criar o
   destino → copiar → dividir → `setval` → **conferir** → `COMMIT`.
3. `CREATE OR REPLACE VIEW public.*` (§5) — daqui o site já volta a ler.
4. Deploy do código novo: push no `main` **e** `vercel --prod`, juntos. O CI roda
   do `main`; a Vercel publica o diretório local. Divergir os dois é como o
   caminho de escrita fica rodando código velho contra schema novo.
5. `python src/atualizar.py --rodada-local` completo, conferindo contra a §1.
6. Religar o `schedule:`.

### 9.9 A janela de observação, e o que ela custa se der errado

`legado_AAAAMMDD` fica **2 a 3 dias**. Durante eles a rodada diária escreve na
estrutura nova — e é esse o ponto: a validação é o pipeline real rodando, não uma
inspeção.

**Reverter depois do commit não é grátis**, e isso precisa estar escrito: o dado
coletado desde a migração vive só na estrutura nova. Voltar ao legado devolve o
estado do dia da migração e **perde as versões coletadas na janela**. Re-raspar
recupera o catálogo atual; não recupera o histórico append-only desses dias. Para
2–3 dias isso é um punhado de snapshots de preço — aceitável, mas é uma escolha
consciente, não um detalhe.

**O drop é passo deliberado, com checklist, nunca automático nem agendado:**

- [ ] duas rodadas completas do `atualizar.py`, no mínimo
- [ ] **uma delas `--rodada-local`** — sem isso o Shotgun e a extração de flyer
      nunca foram exercitados, porque o cron não roda nenhum dos dois
- [ ] teste de fronteira (§10) verde no CI
- [ ] modo conferência (§11) com zero divergências
- [ ] as contagens da §1 reproduzidas
- [ ] site e MCP conferidos à mão

Só então `DROP SCHEMA legado_AAAAMMDD CASCADE`, e o branch pré-migração pode cair
junto (`neonctl branches delete`) — a essa altura ele já cumpriu o papel de
atravessar a janela que a retenção de 6 h não atravessa.

**O `.dump` da §9.1 fica para sempre.** É a única das três redes que sobrevive ao
fim da janela, e a única que não depende da conta do Neon existir.

### 9.10 O append-only sai de graça junto da divisão

É a **única mudança não-aditiva numa tabela que não se pode dropar** — mas, feita
junto da divisão por fonte, não custa nada a mais: as tabelas novas já nascem com
a PK `(id_nativo, origem, raspado_em)` e a coluna `hash`, preenchida na própria
cópia. **A divisão por fonte e o append-only são a mesma migração** (janela #2).

### 9.11 Registro da execução — janela 1 (2026-07-28)

Aplicada. As três redes, na ordem:

| Rede | O que ficou |
|---|---|
| `pg_dump -Fc` | `backups/eventos_20260728_pre-medalhao.dump`, 1,78 MB — 11 tabelas, 2 sequences, 8 índices, a config de busca `pt` |
| Branch do Neon | `pre-medalhao-20260728` (`br-still-hat-acjgs99o`), forkado no LSN `0/1375DF20` |
| Schema de backup | `legado_20260728`, com as 11 tabelas originais intactas |

A transação: 11 `SET SCHEMA` → `public` vazio (conferido) → DDL → 11 `INSERT`
com lista explícita de colunas → 2 `setval` → conferência → `COMMIT`.

**Conferência: as 11 tabelas com contagem E md5 do conteúdo idênticos.**

| | linhas |
|---|---|
| `cru.eventos_raw` | 875 |
| `cru.instagram` | 271 |
| `cru.cinema` | 64 |
| `cru.cinema_extra` | 78 |
| `tratado.eventos` | 457 |
| `tratado.lotes` | 1069 |
| `tratado.filmes` | 39 |
| `tratado.sessoes` | 860 |
| `operacao.execucoes` | 5 (`setval` → próximo id 6) |
| `uso.usuarios` / `uso.acessos` | 0 / 0 |

As quatro views de `public` devolvem exatamente o que a tabela de origem tem.
Depois do commit, conferido contra produção: `consulta.py` responde (20
resultados para "pagode", zero evento passado vazando) e o `test_mcp_server.py`,
agindo como cliente MCP real, passa inteiro — **sem deploy nenhum**, porque a
camada servida manteve os nomes (§9.7).

Os nomes perderam o sufixo `_raw` dentro do `cru`, onde ele é redundante
(`cru.instagram`, `cru.cinema`, `cru.cinema_extra`). `cru.eventos_raw` manteve o
seu de propósito: convive com `tratado.eventos` até a janela 2 desmontá-lo, e
`cru.eventos` ao lado de `tratado.eventos` seria confusão gratuita.

### 9.12 A carga do `locais_df.yaml`

Única, com `autor='migração'` e o motivo apontando para esta spec; o YAML sai do
repo na mesma leva, para não existirem duas fontes da verdade.

---

## 10. Testes

- `tests/base_teste.py` faz `DROP SCHEMA public CASCADE` — passa a dropar os
  seis schemas.
- **Um teste por trilha de fonte:** payload real (fixture do `cru`) → linha
  esperada em `tratado.eventos`. É o teste que hoje não existe para nenhuma
  fonte, e o que a separação torna barato de escrever.
- Era desconhecida → **pulado e vira pendência**, nunca escrito; `raspado_em`
  vindo do `cru`, nunca de `now()`.
- Append-only: payload igual não gera versão; diferente gera; a view `_atual`
  devolve a mais recente; a poda preserva a última de cada `(id_nativo, origem)`.
- Curadoria: correção sobrevive a uma reconstrução completa; revogada não é
  aplicada; `valores_antes` que não bate mais vira pendência; campo fora da
  allowlist é rejeitado.
- **Teste de fronteira** — o que a estrutura promete: depois de um ciclo
  completo, `TRUNCATE tratado.*` + tratamento reproduz a base inteira. Roda no
  CI, não na cabeça de ninguém.
- Os testes existentes passam a qualificar schema nas queries.

---

## 11. Conferência contínua (o que impede a peça de apodrecer)

Uma reconstrução que só roda no dia da migração estará quebrada exatamente nesse
dia — foi o modo de falha da doutrina "base descartável".

O rascunho previa um **modo conferência** rodando entre as fatias 5 e 7: o
tratamento leria o `cru`, normalizaria em memória, compararia com `tratado` e
imprimiria as divergências, sem escrever. Ele existia para cobrir o intervalo de
dias em que a coleta ainda escreveria na prata.

> **Na implementação as fatias 5 e 7 saíram na mesma sessão, então esse
> intervalo não existiu** — e construir o modo conferência seria construir algo
> obsoleto na chegada. O que substitui, e é mais forte, é o **teste de fronteira
> da §10**: `DELETE FROM tratado.*` + tratamento reproduz a base inteira,
> rodando no CI. A conferência é uma amostra que compara; o teste de fronteira é
> a propriedade inteira, verificada.

Depois da inversão, o papel que sobra para uma comparação por rodada é outro —
diff "o que mudou nesta rodada", que é observabilidade de produto, não guarda de
migração. Fica para quando houver pergunta que a justifique.

---

## 12. Decisões tomadas (2026-07-28)

### D1 — `cru` append-only, com dedupe por hash e janela de 90 dias ✅

A bronze guarda a **história**, não só o estado. Custo medido e tratado na §3.5
(~250 MB estabilizados, levando a branch a ~60% do teto de 512 MiB — o teto do
Neon é por branch, não por banco). Onde a política difere, §3.6 explica.

### D2 — A inversão do fluxo entra, como última fatia ✅

A coleta parar de escrever em `tratado.eventos` é o que torna a idempotência
estrutural em vez de convencional. É a maior mudança do pipeline e a **única que
muda comportamento de código** — schemas, views e pastas são mudança de
endereço. Por isso vem por último, com o modo conferência (§11) já rodando e o
teste de fronteira (§10) travando no CI.

### D3 — `public` = só views ✅

Desacopla o formato consumido do armazenado. Começam 1:1. Sem filtro de linha e
sem esconder `organizador` — decisões de outra camada (§5).

### D4 — `operacao` + `uso` separados ✅

Dado de pessoa tem política de retenção e acesso diferente de telemetria.

### D5 — Sexto schema: `curado` ✅

Decisão humana vive fora do que se reconstrói e é reaplicada como último passo
do tratamento (§4). Inclui a referência canônica de locais; **não** inclui
configuração de entrada (§4.3).

### D6 — Uma tabela `cru` por fonte, uma trilha de código por fonte ✅

`coleta/<fonte>.py` → `cru.<fonte>` → `tratamento/<fonte>.py` →
`tratado.eventos`. Resolve por estrutura os rótulos externos e a era do payload
(§3.1), e junta num arquivo só o conhecimento do formato de cada fonte, hoje
partido entre `scrapers/` e `derivar.py` (§7.2). A unificação passa a acontecer
na prata (§2.2). `derivar.py` se dissolve.

### D7 — O bug da `categoria` entra como estanca-sangue (fatia 1)

O dado está errado agora e o FTS come isso. São 206 de 224, e o conserto tem
três passos, não um: o `_normalizar` do Sympla para de mapear `event_type` (que
é `'NORMAL'` em 100% do catálogo), `categoria` entra em `_COLS_PRESERVAR` e os
206 são repostos da bronze. Nenhuma requisição de rede. Ver a correção ao
rascunho na §6.2.

### D8 — Sem ferramenta de migração versionada

Com o `cru` intocável e o `tratado` reconstruível, **mudança não-aditiva na
prata deixa de precisar de migração** — dropa-se e reconstrói. Sobram `cru`,
`curado`, `operacao` e `uso`, onde ela deve ser rara o bastante para caber num
`manutencao/AAAAMMDD_descricao.sql` versionado. Reavaliar na terceira.

### D9 — DDL não é mais aplicado em toda conexão

`conectar(aplicar_schema=False)` por padrão (§7.1).

### D10 — O recorte continua na coleta

Dívida consciente, com o número que a justifica e a mitigação na §6.7.

### D11 — O backup da migração é um schema datado, com validade ✅

`legado_AAAAMMDD` com **todas** as tabelas, e não uma `_legado` dentro do `cru`
(§9.2). Sobre ele, mais duas redes que falham por eixos diferentes: um `.dump`
fora do Neon e um branch do Neon (§9.1). A migração roda em **uma transação com
as conferências dentro dela** (§9.6), em **duas janelas** — a fatia 3 move, a
fatia 5 divide (§9.8) —, e o drop do schema é passo manual com checklist, depois
de 2–3 dias que **incluem uma `--rodada-local`** (§9.9).

O branch é **obrigatório, não precaução**: o plano free retém histórico por
6 horas (§9.1.1), então ele é a única das três redes que preserva o estado
pré-migração ao longo da janela de observação de 2–3 dias.

---

## 13. Ordem de implementação

Fatias independentes, cada uma com valor próprio e reversível:

1. **Estanca-sangue** — `categoria` em `_COLS_PRESERVAR` (§6.2) e o import do
   Playwright para dentro do `raspar()` (§6.6). Não depende de nada.
2. **`sql/` em pastas** — quebrar `schema.sql` em um arquivo por tabela, ainda
   todos em `public`, com o carregador novo. Sem mudança de dado.
3. **Schemas** — `CREATE SCHEMA` + mover as 11 tabelas + views + qualificação no
   código. Sem mudança de lógica. **Primeira janela de migração** (§9.8).
4. **`src/` por estágio** — mover arquivos, ajustar imports, atualizar
   CLAUDE.md, `.mcp.json`, workflow do CI e `vercel.json`. `demo.py` já saiu.
5. **`cru` por fonte + append-only** (§3) e as trilhas de
   `tratamento/<fonte>.py` (§7.2) — o NI-55 propriamente dito, com as guardas de
   era (§6.3) e o modo conferência (§11). Ainda sem inverter: a coleta continua
   escrevendo em `tratado`. **Segunda janela de migração** (§9.8) — a que toca o
   `eventos_raw`, e a de maior risco da spec inteira.
6. **`curado`** — as duas tabelas, `curadoria.py`, a view de pendências e a CLI;
   migração do `locais_df.yaml`.
7. **Inversão do fluxo** (§6.1): a coleta deixa de escrever em `tratado`, o
   "descrever" passa a consultar o `cru` (§6.4), `sumido` vira derivação sobre
   `operacao.coletas` (§8).

   > ⚠️ **NÃO IMPLEMENTADA** (2026-07-28). As fatias 1–6 estão aplicadas,
   > validadas e commitadas; esta ficou. É a maior mudança de comportamento do
   > pipeline e a única que exige mover a normalização das cinco fontes de
   > `coleta/` para `tratamento/`, reescrever `_raspar`/`_descrever`/
   > `_precificar` e converter o tratamento inteiro numa transação — foi
   > iniciada e revertida por inteiro, porque entregá-la pela metade deixaria o
   > pipeline meio invertido, que é pior que não invertido.
   >
   > **O que já está pronto para ela**, das fatias anteriores: `tratado` é
   > escrito por um lugar só (`tratamento/comum.py`), o `cru` guarda payload +
   > rótulos externos + era por fonte, e `comum.aplicar()` já reconstrói todas
   > as colunas derivadas e os lotes a partir do `cru`. **O que falta** é o
   > último passo: as colunas de identidade do evento (nome, datas, local, url)
   > ainda vêm da coleta, não da reconstrução.
   >
   > Enquanto ela não sai, a garantia do NI-55 é PARCIAL: a prata é
   > reconstruível no que é derivado, não no que é identidade.

A fatia 6 pode trocar de lugar com a 5 se a curadoria virar urgente — ela só
depende dos schemas (fatia 3).

---

## 14. Conferência de consumidores externos — feita, com achados

Pergunta: algo fora de `src/`+`api/` consome as tabelas por nome não qualificado
e quebraria com a mudança de schema?

**Resposta: não há consumidor vivo.** A varredura cobriu o repositório inteiro,
inclusive arquivos **não versionados** (script solto, `.sql` local) — nada fora
de `src/`, `api/`, `tests/`, `docs/` e `sql/` cita as tabelas. Mas ela achou
três coisas que valeram decisão:

- **`tests/manuais/explorar_dados.ipynb` já estava quebrado.** Abre `sqlite3` em
  `data/eventos.db`, arquivo que não existe desde a migração para o Neon, em
  11/07. **Mantido** — as consultas são boas e é a ferramenta de exploração da
  Bronze que o projeto não tem em outro lugar. Recebeu um aviso no topo (o que
  quebrou, por quê, e as três mudanças para reviver: `psycopg`, placeholders
  `%s`, nomes qualificados).
- **`tests/spike_bronze/*.py`** — spikes do NI-14, também em `sqlite3` sobre
  JSONL capturados. Registro histórico, não consumidores. Vale notar que
  `rederivar.py` foi o **precedente direto do NI-55**: em 2026-07-10 ele já
  provava que "campo novo não exige re-raspar". A prova existe há 18 dias; o que
  faltou foi a estrutura que obriga.
- **`src/demo.py`** — entrypoint da PoC, defasado (não conhecia Zig, Ticket and
  Go, cinema nem Instagram) e incompatível com a fatia 7. **Removido**, com as
  três menções no CLAUDE.md ajustadas.
- **O front não acessa o banco** — `lib/api.js` fala só com a API interna.

---

## 15. Fora de escopo

- Sistema de migração versionada (§12-D8).
- Interface gráfica de curadoria e tool MCP de escrita (§4.4).
- Mudar o que site ou MCP mostram. Esta spec é estrutural: **o produto não muda
  de comportamento**, exceto pela correção da `categoria` (§6.2), que é conserto
  de bug.
- Mover o recorte de escopo para o tratamento (§6.7).

---

## 16. Ainda em aberto

- **A guarda anti-Bileto (NI-17) fica na COLETA, não no tratamento.** Hoje o
  `_descrever` confere o nome devolvido pelo BFF antes de gravar, porque o id de
  outro namespace devolve um evento alheio sem erro HTTP. Na estrutura nova a
  tentação é mover a guarda para o tratamento (é lá que mora a leitura do
  payload) — e seria errado: payload de outro evento **não pode entrar no `cru`**,
  que é append-only e imutável. Contaminar a bronze é permanente; recusar na
  porta é reversível. A decisão está registrada aqui porque é exatamente o tipo
  de coisa que uma refatoração move sem perceber.
- A conferência de tabelas e scripts que o autor está fazendo em paralelo.
