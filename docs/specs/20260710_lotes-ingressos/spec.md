# Spec — Lotes de ingressos na Prata + tool `detalhar_evento` (NI-18 + NI-13)

> **Status:** especificada e implementada em 2026-07-10.
> **O quê/por quê:** `preco_min` escalar mente por omissão — o `min()` sobre
> todos os lotes colapsa "cortesia feminina até 00h + masculino R$ 49,50" em
> `0,00` (caso real: HOUSE CLUB 13 ANOS, dogfooding no Claude Desktop). A Bronze
> já guarda nome/preço/taxa/estoque de cada lote nas 3 fontes; falta modelar os
> lotes na Prata e dar ao agente um jeito de aprofundar UM evento — a mesma tool
> que devolve os lotes devolve a descrição completa, fechando também o NI-13.

---

## 1. O dado já existe (conferido na Bronze em 2026-07-10)

| fonte, origem | campos por lote |
|---|---|
| sympla, tickets | `name`, `isFree`, `salePriceWithDiscountMonetary.decimal` (R$, **já com taxa**: 49,50 = 45 + 4,50), `feeMonetary.decimal`, `currentAvailableQty` |
| ingresse, tickets | `detail.responseData[].name` (setor) + `type[].name` (lote), `price` (**sem taxa**), `tax`, `status`, `hidden` |
| shotgun, catalogo | `offers[].name`, `price` (total), `availability` |

A perda é de modelagem, não de coleta: a correção inteira é derivação a seco
(`--so-derivar`), sem re-raspar.

## 2. Design

### 2.1 Tabela `lotes` (nova no `sql/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS lotes (
    evento_id TEXT NOT NULL,      -- eventos.id
    ordem     INTEGER NOT NULL,   -- posição no payload (ordem de exibição da fonte)
    nome      TEXT,
    preco     REAL,               -- R$ TOTAL a pagar (com taxa); 0 = grátis
    taxa      REAL,               -- parcela de taxa, quando a fonte separa (NULL no Shotgun)
    gratis    INTEGER NOT NULL,   -- 0/1
    esgotado  INTEGER             -- 0/1; NULL = fonte não informa estoque
);
CREATE INDEX IF NOT EXISTS idx_lotes_evento ON lotes (evento_id);
```

- Sem PK natural (nome de lote pode repetir); `derivar.aplicar()` faz
  `DELETE FROM lotes` + reinsere tudo — idempotência por reconstrução, igual às
  colunas derivadas.
- **Semântica de `preco` normalizada: total a pagar.** Sympla → `decimal` (já
  inclui taxa); Ingresse → `price + tax`; Shotgun → `price` (taxa embutida,
  desconhecida). `taxa` fica separada para o agente poder decompor
  ("R$ 45 + 4,50 de taxa").
- Ingresse: `nome` = `"{setor} — {lote}"` quando o setor (`responseData[].name`)
  existir e diferir do nome do lote. Lotes `hidden` ficam de fora (como hoje).
- Sympla: lotes `show=false` ficam de fora (como hoje).

### 2.2 Derivação (`src/derivar.py`)

Dispatch novo `_LOTES[(fonte, origem)]` → lista de dicts de lote, extraído do
mesmo payload das derivações atuais:

- `(sympla, tickets)`, `(ingresse, tickets)`, `(shotgun, catalogo)`.

`preco_min` e `esgotado` **passam a ser agregações dos lotes** (uma extração
só, sem lógica duplicada):

| coluna | regra nova |
|---|---|
| `preco_min` | mín. de `preco` dos lotes **pagos** (`gratis=0`). Sem lote pago → NULL |
| `tem_gratis` (**nova em `eventos`**) | 1 se existe lote grátis **não esgotado**; senão 0; sem lotes → NULL |
| `esgotado` | inalterada: todos os lotes esgotados → 1 |

Leitura combinada (documentada na docstring do MCP):
`preco_min=38.99, tem_gratis=1` → "grátis em condições (leia os lotes),
pagos a partir de R$ 38,99"; `preco_min=NULL, tem_gratis=1` → evento grátis;
`preco_min=NULL, tem_gratis=NULL` → fonte não informou.

**Coluna nova em `eventos` ⇒ base descartável** (convenção do repo: sem
migração). Apagar `data/eventos.db` e re-raspar (~10 min);
`atualizar._checar_schema` passa a checar `tem_gratis`.

### 2.3 Tool nova `detalhar_evento` (fecha o NI-13, opção (a))

- `consulta.detalhar_evento(url)` → dict único: todos os `CAMPOS` +
  `descricao` **completa** (sem `DESCRICAO_MAX`) + `outras_urls` +
  `lotes: [{nome, preco, taxa, gratis, esgotado}, ...]` (na `ordem` da fonte).
- Lookup por `url` (é o que o agente tem em mãos vindo do `buscar_eventos`):
  casa `eventos.url` exata; se a URL for de um membro não-canônico de grupo de
  dedupe, devolve o canônico do grupo. Não achou → `{"erro": ...}` amigável.
- `mcp_server.py` expõe a tool fina delegando pra `consulta.py`, com docstring
  orientando o fluxo: `buscar_eventos` para listar → `detalhar_evento(url)`
  para aprofundar ("me conta mais dessa festa", "quanto custa pra homem?").
- `buscar_eventos` segue enxuto: ganha `tem_gratis` nos `CAMPOS` e a docstring
  re-explica `preco_min` (menor lote PAGO); a lista de lotes só vem no detalhe.

### 2.4 Decisão deliberada: sem parsing do nome do lote

Nenhuma regra extrai gênero/horário/condição de "CORTESIA FEMININA DA COPA ATÉ
00H" — regex disso é fonte infinita de falso positivo. O nome cru vai ao agente,
que lê e resume ("ingressos masculinos a partir de R$ 45 + taxa"). A Prata só
normaliza o que é aritmético (preço total, taxa, grátis, esgotado).

## 3. Fora de escopo

Meia-entrada/meia-social como conceito (fica no nome do lote), histórico de
lotes (Bronze guarda só o último payload — viraria série temporal, outra
conversa), refresh incremental (NI-15), ranking por preço na busca.

## 4. Plano de teste

- `tests/test_bronze.py`: fixture do caso HOUSE CLUB (cortesia + 2 pagos + VIP)
  → `lotes` com 4 linhas, `preco_min=38.99`, `tem_gratis=1`, `esgotado=0`;
  evento só-cortesia → `preco_min NULL / tem_gratis 1`; cortesia esgotada +
  pago disponível → `tem_gratis=0`; Ingresse `hidden` e setor+lote no nome;
  idempotência do `DELETE`+reinsert.
- `tests/test_mcp_server.py`: chamada real de `detalhar_evento` (descrição
  completa > 300 chars e lotes presentes) e URL inexistente → erro amigável.
- Dogfooding: repetir a pergunta do HOUSE CLUB no Claude Desktop e conferir a
  resposta "grátis p/ mulheres até 00h; pagos a partir de R$ 38,99 c/ taxa".
