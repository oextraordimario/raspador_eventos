# Spec — URLs semânticas para evento e filme (RASCUNHO, não aprovada)

**Data:** 2026-07-29
**Status:** rascunho — as quatro perguntas abertas foram respondidas em 29/07
(§13); nada implementado.
**Backlog:** consome **NI-33** (limpeza de título na derivação); adjacente a
NI-63 (Search Console).

---

## 0. O pedido

Hoje o endereço de um evento é `/evento/sympla~3520331` e de um filme é
`/cinema/29922`. São endereços de dado interno vazados para a barra do
navegador: não dizem nada, e um `~` no meio de um id numérico tem cara de link
encurtado suspeito — o oposto do que um link compartilhado no WhatsApp precisa
parecer.

O pedido é semântico, com as duas formas já definidas:

| entidade | hoje | proposto |
|---|---|---|
| evento | `/evento/sympla~3520331` | `/evento/forro-na-varanda-26-07` |
| filme  | `/cinema/29922`          | `/cinema/homem-aranha-um-novo-dia-2026` |

Evento = **título + dia-mês** (o que a pessoa já lê na página). Filme = **título
+ ano de lançamento**, padrão IMDB — o ano é o que distingue remake e reestreia.

---

## 1. O que existe hoje (medido, não suposto)

### 1.1 O mecanismo atual

`lib/api.js` tem quatro linhas que são todo o esquema de endereçamento:

```js
export const idParaSlug = (id) => id.replaceAll(':', '~')
export const slugParaId = (slug) => slug.replaceAll('~', ':')
```

O id interno é `<fonte>:<id_nativo>`; `:` não vive bem numa rota, então virou
`~`. É **reversível na borda**: o front decodifica e a API busca por igualdade
exata em `public.eventos.id`. Nenhuma consulta ao banco para resolver a rota.

`consulta.detalhar_evento(url)` fareja o argumento: começa com `http` → busca
por `url`; senão → busca por `id`. `consulta.sessoes_filme(filme)` tenta `id`
exato e, se falhar, título parcial (`ILIKE` + `unaccent`), desempatando por
número de sessões futuras.

Os oito pontos que montam endereço:

| arquivo | linha | o que monta |
|---|---|---|
| `app/festas/page.jsx` | 51 | `href` do card de evento |
| `app/sitemap.js` | 25 | uma entrada por evento futuro |
| `app/evento/[id]/page.jsx` | 19, 32 | `canonical`, `pagina` (JSON-LD + compartilhar) |
| `app/cinema/FilmCard.jsx` | 11 | `href` do card de filme |
| `app/cinema/Faixa.jsx` | 29 | `href` do pôster na faixa |
| `app/cinema/[id]/page.jsx` | 86, 111, 179-195 | strip de dias, JSON-LD, base dos `DropFiltro`, "limpar" |
| `app/llms.txt/route.js` | 28 | documenta o padrão `/evento/<id>` |

### 1.2 Os números da base real (sondados em 29/07)

**Eventos** — 551 na `public`, 477 no conjunto **visível** (canônico, sem
ruído, sem sumido, sem cancelado — o que a consulta entrega por padrão):

- slug `titulo-limpo + dd-mm` sobre os 551: **523 distintos** → 28 colisões.
- slug sobre os **477 visíveis: 477 distintos, ZERO colisão**.
- **Toda** colisão observada é entre membros do mesmo grupo de dedupe (ex.: 4
  linhas de `Festa Junina | Roça N' Roll` em 31-07, três não-canônicas) ou
  entre canônico e não-canônico de fontes diferentes (`PIQUE NOVO & BENZADEUS`
  em 22-08: `sympla:3463747` canônico + `ticketandgo:45908`).
- Nenhum nome slugifica para vazio. Nenhum evento sem `start_date` (0/551).
- Comprimento: mediana 32, p95 70, **máximo 99** chars
  (`laboratorio-psy-psylab-samambaia-desvendando-vertentes-e-fortalecendo-a-cena-eletronica-local-18-07`).
- Horizonte: de 2025 a **2027-05-26** — hoje nada passa de 12 meses à frente,
  então `dd-mm` sem ano é único **por acidente**, não por desenho (ver §4).

**Filmes** — 23 em cartaz:

- `titulo + ano`: **23 slugs distintos, zero colisão**, zero título duplicado.
- `ano` preenchido em **23/23**; `cru.tmdb` tem 41 filmes e **0 sem match**
  (`escolhido = None` nunca aconteceu ainda).
- Ids da Ingresso.com são numéricos (`29922`, `28150`) — detectar o formato
  antigo seria trivial, mas a §7 mostra que nem é preciso.
- Já aparece um caso onde o padrão IMDB se justifica sozinho:
  `a-professora-de-piano-relancamento-2002`.

**Churn de nome** (o risco central do slug) — no histórico append-only do cru,
345 eventos têm 2+ versões de catálogo e **8 trocaram de nome** entre a
primeira e a última: **2,3%**. Casos reais:

```
'DOMINGÃO'                        → 'DOMINGÃO | PARTE 2'
'SEXTA DA RESENHA - FEIJÃO NA MESMA CONHA…' → '…CONCHA…'   (typo corrigido)
'Gelada, Pagode e Sentimento…'    → 'Sábado Despedida do Brazólia…'  (renome total)
```

Ou seja: **~2% dos slugs de evento mudam durante a vida do evento**. É o único
problema de verdade desta spec, e a §7.3 propõe a mitigação.

**Tráfego atual** (PostHog, 30 dias): `/evento/*` teve **23 pageviews de 2
pessoas** em 8 caminhos distintos; `/cinema/<id>` teve **zero** (a página é de
27/07). O site mora em `raspador-eventos.vercel.app`, sem Search Console
(NI-63). Conclusão: **a janela para trocar as URLs é agora** — o custo de
quebrar endereço indexado é aproximadamente zero e só cresce daqui pra frente.

---

## 2. A forma do slug

### 2.1 Slugificação (uma função, um lugar)

```
NFKD → descarta combining marks (ç→c, ó→o) → minúscula
   → [^a-z0-9]+ → '-'  → colapsa → tira '-' das pontas
```

Verificado contra a base: `Roça N' Roll` → `roca-n-roll`; `Bernardo Rosa Trio —
O melhor do Pop Rock` → `bernardo-rosa-trio-o-melhor-do-pop-rock`; `Galpão 17
Rock Festival` → `galpao-17-rock-festival`. Emoji e pontuação somem. Se o
resultado ficar vazio (nome só com emoji — não existe hoje), cai no
`slugificar(id)`, que nunca é vazio.

### 2.2 Evento: `<titulo>-<dd>-<mm>`

- `titulo` = **título limpo** (`tituloLimpo`), não o nome cru. Sem isso,
  `Forró na Varanda | 28.07 | Varanda do Contexto` viraria
  `forro-na-varanda-28-07-varanda-do-contexto-28-07` — data duas vezes e o
  local no meio. É o que amarra esta spec ao NI-33 (§5).
- `dd-mm` = dia **local de Brasília puro**, o mesmo que o `diaMes()` mostra na
  página. **Não** é o dia da vida noturna (corte às 6h): a festa que começa 1h
  de sábado mostra `01/08` no `<h1>` e tem que mostrar `01-08` na URL. O slug
  copia a tela, não a regra de janela.
- Sem ano por padrão (ver a escada da §4).

### 2.3 Filme: `<titulo>-<ano>`

- `titulo` = `titulo` da Ingresso.com, como já aparece na página.
- `ano` = `filmes.ano`, que vem do **TMDB** (`release_date[:4]`).
- `ano` NULL → slug **sem** o sufixo (`/cinema/mil-luas`). Hoje não acontece
  (23/23 com ano), mas o matching do TMDB é conservador de propósito e conteúdo
  alternativo (ópera, show gravado, sessão especial) é o candidato natural a
  não casar. A §6.3 faz o slug-sem-ano continuar resolvendo depois que o ano
  aparece, então isso não gera link morto.

### 2.4 Teto de comprimento — **60 chars** (decidido)

99 chars é feio e é o que a base tem hoje. O título é cortado em **60 chars na
fronteira de palavra** antes de anexar o sufixo, que nunca é cortado:

```
laboratorio-psy-psylab-samambaia-desvendando-vertentes-18-07
```

A mediana da base é 32, então ~95% dos slugs não mudam. O corte aumenta
marginalmente a chance de colisão, que a escada da §4 resolve — e o teto entra
**antes** da escada, para o desempate contar o slug já cortado.

---

## 3. Onde o slug nasce: uma coluna na prata

### 3.1 As três opções, e por que a coluna ganha

| # | onde | como resolve a rota | veredito |
|---|---|---|---|
| A | só no front (JS calcula do `nome`+`start_date`) | teria que recalcular no Python para achar a linha | **não**: duas implementações da mesma regex; divergência = 404 |
| B | a seco, na hora da consulta (busca candidatos do dia e slugifica cada um) | scan de ~40 linhas/dia + slugificação em Python | funciona, mas ainda precisa da regra em JS para montar o `href`, e o desempate fica não determinístico |
| C | **coluna `slug` na prata, escrita pelo tratamento** | `WHERE slug = %s`, índice único | **sim** |

Com (C) o slug é **dado derivado**, igual a `bairro`, `tipo` e `dedupe_grupo`:
nasce uma vez, na camada que já é dona de derivar, e o front nunca calcula nada
— ele só usa `ev.slug` que a API entregou. O JS de slugificação **deixa de
existir**. É também o que permite garantir unicidade por **índice do banco**, e
não por convenção.

### 3.2 Schema

`sql/tratado/eventos.sql`:

```sql
slug TEXT,   -- endereço público (<titulo-limpo>-<dd>-<mm>); ver src/tratamento/slug.py
-- e, no bloco aditivo do fim do arquivo:
ALTER TABLE tratado.eventos ADD COLUMN IF NOT EXISTS slug TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_slug ON tratado.eventos(slug);
```

`sql/tratado/filmes.sql`: idem, `slug TEXT` + índice único.

`sql/public/eventos.sql` e `sql/public/filmes.sql`: `slug` entra **no FIM** da
lista de colunas da view — `CREATE OR REPLACE VIEW` sabe acrescentar coluna ao
final, mas não reordenar (o arquivo já avisa isso em comentário; o deploy falha
com *cannot change name of view column*).

### 3.3 O passo novo: `src/tratamento/slug.py`

Um módulo a seco, com `aplicar(con)` devolvendo `{"eventos": n, "filmes": n,
"desempates": [...]}`. Duas armadilhas conhecidas do projeto, e como escapar
das duas:

1. **`slug` NÃO entra em `comum.COLS_EVENTO`.** Aquela lista é reescrita
   inteira a cada reconstrução, e a coluna seria zerada toda rodada — é
   exatamente a nota que a coluna `tipo` carrega no schema. O dono do `slug` é
   este passo, como o `enriquecer` é dono de `ruido`/`dedupe_*`.
2. **O índice único vs. reatribuição.** Reatribuir slug com o índice ativo pode
   colidir no meio do caminho (A ganha o slug que B tinha). Então o passo é:
   `UPDATE tratado.eventos SET slug = NULL` → calcula tudo em Python →
   `executemany` de um `UPDATE ... SET slug = %s WHERE id = %s`. Duas
   instruções, ~550 linhas, dentro da transação do ciclo. Nenhum leitor vê o
   NULL (MVCC).

### 3.4 Onde entra no ciclo

`tratamento/ciclo.py` hoje: `comum` → `instagram` → `cinema` → `sumido` →
`enriquecer` → `curadoria` → `busca` → **um commit**.

O slug entra **depois da curadoria e antes da busca**:

- **depois do `enriquecer`**, porque a escada de desempate precisa saber quem é
  `dedupe_canonico` (o canônico é quem fica com o slug limpo);
- **depois da `curadoria`**, porque `nome` e `start_date` são campos curáveis —
  se uma pessoa corrigiu o nome à mão, a URL tem que refletir a correção;
- **depois do `cinema`**, incluindo o `UPDATE` do TMDB que roda dentro dele (é
  de lá que sai o `ano`);
- vale também no `--so-enriquecer`, que roda curadoria (a ordem acima já cobre).

Isso vira o **quinto ponto** da lista "a ordem importa em N pontos" da
docstring do `ciclo.py`.

---

## 4. Unicidade e desempate — a escada

Atribuição em ordem determinística: **`start_date ASC, dedupe_canonico DESC,
ruido ASC, id ASC`**. `start_date` primeiro é o que dá a propriedade que
importa: **evento que já aconteceu nunca perde o slug que tinha** para um
evento novo — o passado não se move, então URL antiga não é roubada.

Para cada evento, a primeira forma livre ganha:

1. `titulo-dd-mm` — o caso de 100% da base visível hoje;
2. `titulo-dd-mm-aaaa` — resolve colisão **entre anos** ("Aniversário do Bar"
   em 15-03 de 2026 e de 2027). Legível, e o ano é informação de verdade;
3. `titulo-dd-mm-2`, `-3`, … — resolve colisão **no mesmo dia**, que hoje só
   ocorre entre canônico e duplicata do mesmo evento. Quem cai numa dessas é
   sempre uma linha que o site não linka (§7.2 mostra que ela 308 para o
   canônico), então o `-2` praticamente não aparece em endereço de verdade.

Filmes: mesma escada, sem o degrau do ano (o ano já está no slug) — `-2` direto,
ordenado por `id ASC`.

O passo **reporta** os desempates no retorno, e o relatório da rodada os
imprime: desempate virando rotina é sintoma (de dedupe frouxo ou de teto de
comprimento agressivo), e sintoma silencioso é o que esta base já pagou caro
para aprender a não ter.

---

## 5. A dependência: NI-33 entra nesta leva (decidido)

O slug do evento precisa do título limpo, e `tituloLimpo()` mora em
`lib/formato.js` — JavaScript, no front, servindo só à exibição. **Decidido:
fazer o NI-33 inteiro** em vez de portar a regra só para o slug.

O tratamento passa a gravar `tratado.eventos.nome` **já limpo** — é o que o
próprio item de backlog prescreve ("sobrescrever `eventos.nome` na derivação é
reversível por `--so-derivar`", que é o padrão de toda coluna derivada) — e o
front deleta a função, usando `ev.nome` direto. Consequências:

- slug e `<h1>` **não podem** divergir: vêm da mesma string. A alternativa
  (duas cópias equivalentes da mesma regex, mantidas à mão) teria a URL dizendo
  uma coisa e o título outra na primeira vez que uma das duas fosse editada;
- o MCP passa a receber o mesmo título que o site — é exatamente a dívida que o
  NI-33 descreve (hoje o agente recebe o nome sujo);
- o FTS indexa o nome limpo: perde só os tokens de data, que não servem para
  busca;
- o **dedupe melhora**: `Festa X | 28.07` e `Festa X` param de ser nomes
  diferentes — e o dedupe cross-fonte é justamente onde isso pesa.

**O único risco de comportamento desta spec está aqui**: o agrupamento de
duplicatas pode mudar. Por isso é **fatia própria (a nº 2 da §9), antes de
qualquer coisa de slug**, com este protocolo:

1. antes: gravar a contagem de `dedupe_grupo` distintos, de não-canônicos e de
   `ruido` no estado atual;
2. `--so-derivar`;
3. depois: comparar as três contagens e **inspecionar à mão** todo grupo novo
   (nome limpo aproximando dois eventos que antes não se viam) — é o resultado
   esperado, mas tem que ser verificado, não presumido;
4. `tests/test_enriquecer.py` como rede (ruído + dedupe + efeito na consulta).

Se o passo 3 mostrar agrupamento errado, a fatia volta atrás sozinha
(`--so-derivar` reconstrói a prata do cru) sem bloquear o resto da spec — o
slug passaria a usar `texto.titulo_limpo()` na hora de gerar, e o NI-33 volta
para o backlog.

NI-33 é `prioridade=alta, rank=2, esforço=M`, pendente desde 27/07, e sai do
backlog quando esta fatia subir.

---

## 6. Resolução — como a rota vira registro

### 6.1 Camada canônica (`src/servico/consulta.py`)

`detalhar_evento(url)` ganha um terceiro caso no farejador que já existe:

```
começa com 'http'  → busca por url        (é o que o MCP passa)
contém ':'         → busca por id         (formato interno / endereço antigo)
senão              → busca por slug       (o endereço público novo)
```

Slug nunca contém `:` e nunca começa com `http`; id interno sempre contém `:`.
O farejamento continua num lugar só, e a `api/dados.py` segue sem lógica
própria (repassa `?url=` como veio — o nome do parâmetro fica, por compatibilidade
com o MCP; a docstring passa a chamá-lo de "identificador").

`sessoes_filme(filme)` ganha o mesmo degrau, **antes** dos que já existem:
`slug` exato → `id` exato → título parcial (`ILIKE`, que o agente usa).

`slug` entra em `CAMPOS` (eventos) e `CAMPOS_FILME`. É o que faz a lista, o
sitemap e o detalhe conhecerem o endereço canônico sem calcular nada.

### 6.2 O que a API devolve

Nada de rota nova. `slug` aparece no payload de `/eventos`, `/evento`,
`/filmes` e `/sessoes` porque entrou nos `CAMPOS`. `_limpar()` não mexe nele
(não é `organizador`, não é `descricao`).

### 6.3 O caso do filme sem ano

Se o slug pedido não casar exatamente, e ele for **prefixo de exatamente um**
slug de filme seguido de `-<4 dígitos>`, resolve nesse filme (e a §7.2 manda um
308 para o endereço com ano). Assim `/cinema/mil-luas`, compartilhado antes do
TMDB responder, continua chegando em `/cinema/mil-luas-2026`. Um só candidato,
senão erro — sem adivinhação.

---

## 7. Compatibilidade — os endereços que já existem

### 7.1 Uma regra, nenhum farejamento de formato no front

```
resolve o parâmetro da rota (slug | id antigo | id numérico | título)
se não achou                       → notFound()
se ev.slug existe e != parâmetro   → permanentRedirect(`/evento/${ev.slug}`)
senão                              → renderiza
```

Essa regra sozinha cobre **todos** os casos, sem nenhum `if` sobre formato:

- `/evento/sympla~3520331` → 308 → `/evento/samba-de-chinelo-…-01-08`;
- `/cinema/29922` → 308 → `/cinema/homem-aranha-um-novo-dia-2026`;
- `/cinema/mil-luas` → 308 → `/cinema/mil-luas-2026` (§6.3);
- **duplicata → canônico**: hoje `/evento/<id-não-canônico>` serve o conteúdo
  do canônico **no endereço errado** (conteúdo duplicado para o buscador, com
  `canonical` apontando para o endereço errado — bug pré-existente que esta
  regra conserta de graça);
- `ev.slug` NULL (rodada não passou) → não redireciona, renderiza. Sem laço.

`permanentRedirect()` do Next devolve 308, que o Google trata como 301.

### 7.2 Onde a regra mora

Em `app/evento/[id]/page.jsx` e `app/cinema/[id]/page.jsx`, logo depois do
fetch — os dois já fazem `notFound()` ali. Middleware está fora de questão: ele
não tem como saber o slug sem consultar a base.

Os diretórios passam a se chamar `app/evento/[slug]/` e `app/cinema/[slug]/`
(o parâmetro é o que aparece no código; `[id]` mentiria).

### 7.3 O link compartilhado que morre — `operacao.slugs` (decidido)

2,3% dos eventos trocam de nome (§1.2) → o slug muda → o link que alguém
mandou no WhatsApp 404. **Decidido: entra nesta leva**, como fatia própria (a
nº 6 da §9 — descartável sem prejuízo do resto, mas não descartada):

`operacao.slugs` (append-only, nunca se dropa — é histórico, não derivado):

```sql
CREATE TABLE IF NOT EXISTS operacao.slugs (
    slug       TEXT PRIMARY KEY,
    entidade   TEXT NOT NULL,   -- 'eventos' | 'filmes'
    registro_id TEXT NOT NULL,
    visto_em   TEXT NOT NULL
);
```

O passo do §3.3 registra todo slug que atribui (upsert por `slug`, `visto_em`
avança). A resolução, **só no caminho triste** (slug não achado na prata),
consulta essa tabela e 308 para o endereço atual. Custa um `INSERT ... ON
CONFLICT` por evento por rodada e um `SELECT` por 404. É o que transforma "URL
bonita" em "URL bonita que não quebra".

Sem isso, o endereço antigo `<fonte>~<id>` continuaria funcionando para sempre
(§7.1), mas o slug antigo não — e é o slug que as pessoas compartilham.

Três detalhes que a implementação não pode esquecer:

- a tabela mora em `operacao` porque é **artefato nosso, não derivado**: não se
  reconstrói do cru (o nome antigo do evento existe no cru, mas a regra que
  gerou o slug daquela época pode não existir mais). **Nunca se dropa.**
- **o `registro_id` é atualizado no conflito**, o `slug` não: se um slug for
  reatribuído a outro evento pela escada da §4, o histórico aponta para o dono
  atual e não gera redirecionamento errado;
- o 308 do histórico só dispara quando **o registro apontado ainda existe** na
  prata; senão, `notFound()` normal.

### 7.4 Os outros consumidores

| onde | mudança |
|---|---|
| `app/festas/page.jsx:51` | `href={`/evento/${ev.slug}`}` — `idParaSlug` sai |
| `app/sitemap.js` | idem; **oportunidade**: hoje o sitemap não lista filme nenhum (fora de escopo, virar item de backlog) |
| `app/evento/[slug]/page.jsx` | `canonical` e `pagina` passam a usar `ev.slug` (não o parâmetro da URL — senão o endereço antigo se autodeclara canônico) |
| `app/cinema/FilmCard.jsx`, `Faixa.jsx` | `f.slug` |
| `app/cinema/[slug]/page.jsx` | `hrefDia`, `base` dos `DropFiltro`, "limpar" e JSON-LD passam a usar `filme.slug` |
| `lib/api.js` | `idParaSlug`/`slugParaId` **morrem** |
| `app/llms.txt/route.js` | documenta `/evento/<titulo>-<dia>-<mes>` |
| PostHog | `$pathname` muda; nenhum evento nosso carrega id de evento (usam título/nome), então só a série histórica de pageview por caminho se parte. Vale registrar uma anotação no PostHog na data do deploy. |

---

## 8. Mudanças por camada (resumo)

| camada | arquivos |
|---|---|
| SQL | `sql/tratado/eventos.sql`, `sql/tratado/filmes.sql` (coluna + índice único), `sql/public/eventos.sql`, `sql/public/filmes.sql` (coluna no fim), **novo** `sql/operacao/slugs.sql` |
| base | `src/base/texto.py` (`slugificar`, `titulo_limpo`) |
| tratamento | **novo** `src/tratamento/slug.py`; `ciclo.py` (um passo); `comum.py` (aplicar o título limpo no caminho do upsert — NI-33) |
| serviço | `consulta.py` (farejador + `CAMPOS`/`CAMPOS_FILME`) |
| API | `api/dados.py` (só a docstring; nenhum código novo) |
| front | `lib/api.js`, `lib/formato.js` (perde `tituloLimpo`), `app/festas/page.jsx`, `app/sitemap.js`, `app/evento/[slug]/*`, `app/cinema/[slug]/*`, `app/cinema/FilmCard.jsx`, `Faixa.jsx`, `app/llms.txt/route.js` |
| testes | **novo** `tests/test_slug.py`; ajustes em `test_api_dados.py`, `test_cinema.py`, `test_bronze.py` |
| docs | `CLAUDE.md` (o endereçamento novo + a armadilha do `COLS_EVENTO`), backlog (NI-33 sai) |

Nenhuma mudança destrutiva: as duas colunas são aditivas e `tratado` é
reconstruível. `cru`, `curado` e `uso` não são tocados.

---

## 9. Ordem de implementação (cada fatia sozinha em pé)

1. **`texto.slugificar` + `texto.titulo_limpo` + teste unitário** — nada
   integrado ainda; os casos vêm dos nomes reais da §1.2.
2. **NI-33** — título limpo na base, `--so-derivar`, protocolo de verificação do
   dedupe (§5). O site fica idêntico (ele já limpava na exibição), então esta
   fatia é invisível para quem usa — de propósito.
3. **Coluna + `slug.py` + passo no ciclo** — `--so-derivar` e conferir na base:
   477 slugs únicos, zero desempate, e o **teste de fronteira**: apagar a prata,
   reconstruir, os slugs voltam idênticos.
4. **`consulta.py` + API** — resolver por slug, `slug` nos campos. O site ainda
   usa o endereço antigo e continua funcionando (nada quebra nesta fatia).
5. **Front** — renomear os diretórios, trocar os `href`, o 308, canonical,
   sitemap, llms.txt. É aqui que a URL muda de verdade.
6. **`operacao.slugs`** — histórico + resolução no caminho triste. Vem depois do
   front de propósito: o valor dela só existe quando o slug já é o endereço
   real, e ela é a única fatia que pode ficar para uma segunda leva sem deixar
   nada quebrado no meio.

---

## 10. Plano de teste

**`tests/test_slug.py`** (novo, banco `eventos_teste`):

- slugificação: acento, `ç`, apóstrofo (`Roça N' Roll`), emoji, pontuação,
  nome que vira vazio, teto de comprimento;
- título limpo: os casos que o NI-33 protege (`Rock dos 80/90`, `Baile 24/7`,
  `Aniversário 10/10 anos` não podem perder o número);
- escada: dois eventos mesmo nome/mesmo dia → um leva `-2`; mesmo nome, mesmo
  dia-mês, anos diferentes → o segundo leva o ano; o **canônico** fica com o
  slug limpo;
- **estabilidade**: rodar `aplicar` duas vezes não muda nenhum slug
  (idempotência comparando **todas** as colunas que o passo escreve — a
  armadilha do `dedupe_score`, com `ORDER BY` na verificação);
- **estabilidade sob reconstrução**: apagar a prata, reconstruir do cru, os
  slugs voltam iguais (é o teste que prova que a URL não muda a cada rodada);
- evento no passado mantém o slug quando um homônimo futuro entra.

**`tests/test_api_dados.py`**: `/evento?url=<slug>` resolve; o payload da lista
e do detalhe traz `slug`; slug de duplicata devolve o canônico.

**`tests/test_cinema.py`**: `buscar_filmes` traz `slug`; `sessoes_filme` aceita
slug, id e título; filme sem `ano` resolve pelo slug curto.

**`tests/test_bronze.py`**: o teste de fronteira já apaga a prata e reconstrói —
acrescentar a asserção de que `slug` volta preenchido e único.

**No navegador** (`npm run dev` + API local, medindo por `127.0.0.1`):
`/festas` → clicar um card → URL semântica; endereço antigo com `~` → 308;
`/cinema/<id numérico>` → 308; `view-source` conferindo que `canonical` e o
`url` do JSON-LD apontam para o slug; compartilhar copia o endereço novo.

---

## 11. Riscos e decisões registradas

| risco | tamanho | resposta |
|---|---|---|
| slug muda quando a fonte renomeia o evento | **real, 2,3%** | §7.3 (`operacao.slugs`), fatia 6 |
| endereço indexado quebra | ~zero hoje (23 pageviews/30d, sem domínio próprio, sem Search Console) | 308 permanente; e a janela para fazer isso só encolhe |
| colisão de slug esconde um evento | zero na base visível de hoje | índice único + escada + desempate reportado no relatório |
| `slug` entrar em `COLS_EVENTO` por descuido e zerar toda rodada | é a armadilha que a coluna `tipo` já documenta | comentário na coluna + teste de reconstrução |
| dedupe mudar de comportamento com o título limpo (NI-33) | **médio — o único risco de comportamento da spec** | fatia 2, isolada, com o protocolo de verificação da §5 |
| série histórica de pageview por caminho se partir no PostHog | pequeno | anotação no PostHog na data do deploy |

**Decisões que já estão tomadas nesta spec** (não são perguntas): o slug é
coluna derivada na prata (§3.1); o dia do slug é o dia local puro, não o corte
das 6h (§2.2); a resolução é uma regra só, sem farejar formato no front (§7.1);
o `slug` fica fora de `COLS_EVENTO` (§3.3).

---

## 12. Fora de escopo (viram backlog, não entram aqui)

- Sitemap de filmes (hoje o `app/sitemap.js` não lista nenhum).
- MCP entregar o endereço da página do site junto do link da fonte — o slug
  torna isso trivial, mas é outra decisão de produto.
- Renomear qualquer outra rota (`/festas`, `/cinema`, `/sobre`).

---

## 13. As quatro decisões de 29/07

As perguntas abertas do rascunho, respondidas antes de implementar. Ficam
registradas porque cada uma tinha uma alternativa defensável, e daqui a três
meses o motivo é mais útil que a escolha.

**D1 — o título limpo vai para a base (NI-33 inteiro), não só para o slug.**
Duas cópias da mesma regex em duas linguagens divergem na primeira vez que
alguém edita uma delas, e o sintoma seria a URL discordando do `<h1>`. Como
efeito colateral, o agente do MCP passa a receber o mesmo título que o site — a
dívida que o NI-33 registrou em 27/07. Detalhe e protocolo de verificação na
§5; é a única fatia com risco de comportamento.

**D2 — o prefixo do evento continua `/evento/<slug>`.** A alternativa era
`/festas/<slug>`, simétrica ao `/cinema/<slug>`. Assimetria aceita de propósito:
`/festas/` no meio da URL de um show ou de uma roda de samba mentiria, e
`/evento/nome-da-festa` se explica sozinho num link colado no WhatsApp. A hora
de mudar isso era esta — não se troca a URL duas vezes —, e a decisão é: não
muda.

**D3 — teto de 60 chars no título do slug** (§2.4). A mediana da base é 32, o
máximo é 99; ~95% dos slugs não mudam, e o caso que motivou a spec (o link com
cara de spam) é exatamente o que o teto conserta.

**D4 — `operacao.slugs` entra nesta leva** (§7.3). 2,3% dos eventos trocam de
nome: sem o histórico, "URL bonita" duraria até o primeiro renome de um evento
que alguém compartilhou. É a fatia 6, a única que poderia esperar — e não vai.
