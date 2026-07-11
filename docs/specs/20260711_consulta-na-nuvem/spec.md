# Spec — Fase 0b: consulta na nuvem (NI-09 migração para Neon + NI-20 MCP remoto)

> **Status:** CONCLUÍDA em 2026-07-11 (spec e implementação no mesmo dia):
> migração, testes, primeira carga real no Neon, MCP HTTP e deploy em produção
> na **Vercel** (`https://raspador-eventos.vercel.app`, entrypoint
> `api/index.py`, envs no projeto; smoke com cliente MCP real passou — o risco
> do §4.3 não se materializou, só exigiu desligar a proteção de DNS rebinding
> do SDK, que é para servidor local). Connector plugado no celular do autor e
> validado: consulta funcionando com o PC desligado (critério do §7).
> **O quê/por quê:** PRD §5 (restrição de disponibilidade, achado do dogfooding de
> 2026-07-10) e §6 Fase 0b. O read-path não pode depender do PC do autor ligado:
> a base migra para Postgres gerenciado (Neon, free tier) e a camada de consulta
> vira um MCP remoto (HTTP) em serverless free tier, plugável como connector no
> agente do celular. O write-path segue manual e local: o `atualizar.py` roda no
> PC do autor e grava direto na base remota. NI-09 e NI-20 são a mesma entrega
> na prática — por isso uma spec só.

---

## 0. Decisão de banco — reavaliação feita, Neon mantido

O NI-09 previa 30 min de análise antes de destravar a decisão. Feita em
2026-07-11, com três opções na mesa:

| Opção | Ganho | Custo |
|---|---|---|
| **Neon (Postgres)** — decisão travada no PRD §7 | dialeto padrão; pronto para multi-escritor (Actions, NI-10) e instrumentação (NI-11) da Fase 1 | migração real: driver, FTS5 → tsvector, ~40 pontos de SQL em 6 módulos, testes passam a exigir Postgres |
| Turso/libSQL (SQLite gerenciado) | mantém dialeto e FTS5 | `create_function` (norm_ts) não roda em conexão remota; cliente Python e empresa em transição (vendor risk) |
| Arquivo SQLite publicado (write local → upload do `.db` → serverless lê read-only) | zero migração de SQL, testes intactos | adia a migração em vez de eliminá-la; read-path não pode escrever (bloqueia a instrumentação da Fase 1) |

**Decisão (do autor, 2026-07-11): manter Neon.** O retrabalho é pago uma vez e
deixa a base pronta para as Fases 1/2; as alternativas só empurram a mesma
migração para frente. As duas rejeitadas ficam registradas aqui — não reabrir
sem fato novo.

## 1. Topologia

```
  PC do autor (write, sob demanda)              Nuvem (read, sempre no ar)
  ┌─────────────────────────────┐        ┌────────────────────────────────┐
  │ python src/atualizar.py     │ UPSERT │  Neon (Postgres free tier)     │
  │ (raspagem + pipeline igual  ├───────►│  banco eventos                 │
  │  ao de hoje)                │        │  banco eventos_teste (testes)  │
  └─────────────────────────────┘        └───────────────┬────────────────┘
                                                         │ SELECT (URL pooled)
                                          ┌──────────────▼────────────────┐
                                          │ MCP remoto (streamable HTTP,  │
                                          │ serverless free tier,         │
                                          │ prefixo de rota secreto)      │
                                          └──────────────┬────────────────┘
                                                         ▼
                                          agente no celular (connector)
```

- **Sem caminho SQLite residual:** a base local morre; `data/eventos.db` deixa
  de existir e o código fica Postgres-only. Backend duplo seria complexidade
  permanente para servir um período de transição de dias.
- **Segredos por variável de ambiente**, nunca no repo:
  - `EVENTOS_DB_URL` — connection string do banco `eventos`. No PC do autor
    (write) e no serverless (read, usando a **URL pooled** do Neon), cada um
    com a sua.
  - `EVENTOS_DB_URL_TESTE` — banco `eventos_teste` do mesmo projeto Neon; só os
    testes usam (seção 3).
  - `MCP_SEGREDO` — prefixo de rota do MCP remoto (seção 4.2).

## 2. NI-09 — migração do dialeto (SQLite → Postgres)

### 2.1 Driver: psycopg 3

`psycopg[binary]` no `requirements.txt`. Escolhido porque `Connection.execute()`
existe e devolve cursor — o padrão `con.execute(...).fetchall()` usado em todo o
projeto migra sem mudar de forma. `row_factory=dict_row` substitui
`sqlite3.Row` (os acessos `r["col"]` e `dict(r)` continuam válidos).
Placeholders `?` viram `%s` em todos os módulos. Os `con.commit()` existentes
seguem no lugar (psycopg também abre transação implícita).

### 2.2 Datas: normalizar na escrita mata o `norm_ts` do SQL

Hoje a `consulta.py` registra `norm_ts` como função SQL em runtime
(`create_function`) para comparar os formatos mistos (`+00:00` vs `.000Z`).
Postgres não tem equivalente barato — e não precisa: o `upsert_eventos` passa a
aplicar `tempo.norm_ts` em `start_date`/`end_date`/`raspado_em` **antes de
gravar**. Invariante novo (comentado no schema): essas colunas seguem TEXT, mas
só contêm ISO UTC no formato do `datetime.isoformat()` (`+00:00`) — comparação
e ordenação lexicais voltam a ser seguras.

- `consulta.buscar_eventos` normaliza `data_inicio`/`data_fim` em Python
  (`tempo.norm_ts`) antes do bind e compara `e.start_date >= %s` direto; o
  `create_function` some. Parâmetro que não parseia vira NULL e a comparação
  exclui tudo — mesmo comportamento de hoje.
- `tempo.py` fica intacto como parser Python (`instante` continua usado por
  atualizar/enriquecer/derivar); só o docstring do `norm_ts` muda (não é mais
  função SQL — é a normalização de escrita).
- Não usar `timestamptz`: obrigaria converter datetime → string em todos os
  pontos de leitura para manter o contrato JSON da consulta. TEXT normalizado
  entrega a mesma corretude tocando um ponto só (o upsert).

### 2.3 FTS: FTS5 → `tsvector`, reaproveitando o passo de rebuild

- **Config de busca `pt`** criada no `schema.sql` (extensão `unaccent` +
  `portuguese_stem`, via bloco `DO` idempotente): preserva a insensibilidade a
  acento que o FTS5 (unicode61) dava de graça — "eletronica" tem que continuar
  achando "eletrônica". Ganho novo: stemming ("festas" acha "festa").
- **Coluna `busca tsvector`** em `eventos` + índice GIN. **Não** é coluna
  gerada: `unaccent()` não é IMMUTABLE e o Postgres rejeitaria. Quem a preenche
  é o `sql/reconstruir_fts.sql` reescrito (`UPDATE eventos SET busca =
  to_tsvector('pt', coalesce(nome,'') || ' ' || ...)` sobre os mesmos 4 campos
  de hoje: nome, categoria, atracoes, descricao) — o pipeline já chama
  `store.reconstruir_fts` no fim de toda rodada, então a arquitetura não muda.
  Sem pesos (`setweight`): a consulta ordena por data, não por relevância.
- **Query:** o subquery `rowid IN (... MATCH ?)` vira
  `e.busca @@ websearch_to_tsquery('pt', %s)`. A sintaxe exposta ao agente
  muda de FTS5 para websearch (`OR` maiúsculo funciona igual; frase entre
  aspas; `-termo` exclui) — atualizar o docstring da tool `buscar_eventos`.
- **Validação de paridade:** rodar as consultas canônicas ("pagode",
  "funk OR techno", "eletrônica" com e sem acento) antes e depois e comparar
  resultados. Se o stemming português degradar algo, o fallback documentado é
  copiar a config de `simple` (sem stemming/stopwords) em vez de `portuguese`
  — comportamento idêntico ao FTS5 atual.

### 2.4 Mapeamentos pontuais (o resto da migração)

| Hoje (SQLite) | Depois (Postgres) | Onde |
|---|---|---|
| `AUTOINCREMENT` | `BIGINT GENERATED ALWAYS AS IDENTITY` | `execucoes` |
| `REAL` | `DOUBLE PRECISION` | schema |
| `PRAGMA table_info(eventos)` | `information_schema.columns` | `atualizar._checar_schema` |
| `GROUP_CONCAT(o.url)` | `string_agg(o.url, ',')` | `consulta.py` (2×) |
| `SUM(descricao IS NOT NULL)` | `COUNT(descricao)` | relatório do `atualizar.py` |
| `fetchone()[0]` | alias na query + acesso por nome (dict_row) | `demo.py` |
| `store.DB_PATH` (prints/redirecionamento) | some; módulo expõe a URL em uso (sem credencial nos prints) | `store.py`, relatório, testes |

`ON CONFLICT ... DO UPDATE SET ... excluded.*`, `executemany`, `LIMIT %s`,
inteiros 0/1 nas flags e as PKs compostas migram sem mudança de forma. As
colunas JSON de `execucoes` (`fontes`/`passos`/`erros`) **seguem TEXT** com
`json.dumps`/`loads` — jsonb seria só cosmético e mexeria na adaptação de tipos.

### 2.5 `conectar()` e o schema

`store.conectar()` mantém o contrato: conecta (na URL de `EVENTOS_DB_URL`) e
aplica `sql/schema.sql`, que continua idempotente (`IF NOT EXISTS`; a config
`pt` via bloco `DO`). O script roda como um `execute()` multi-statement —
uma viagem de rede a mais por conexão, aceitável na 0b; otimizar (aplicar
schema só no write-path) apenas se a latência de consulta incomodar de fato.
O read-path serverless usa a URL **pooled** do Neon (PgBouncer), que é a
recomendação para conexões curtas de função serverless.

**Base descartável continua sendo a convenção** (sem migrações): "apagar
`data/eventos.db`" vira `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`
no banco `eventos` (DBeaver/psql) e re-raspar. Documentar no CLAUDE.md.

## 3. Testes: banco descartável no Neon

Os 4 scripts de teste hoje redirecionam `store.DB_PATH` para um arquivo
temporário. O equivalente:

- Banco **`eventos_teste`** no mesmo projeto Neon (free tier permite múltiplos
  bancos), apontado por `EVENTOS_DB_URL_TESTE`.
- Cada script começa exigindo a variável (**aborta com instrução se ausente** —
  teste nunca pode cair no banco de produção por omissão), aponta o `store`
  para ela e roda `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` antes do
  primeiro `conectar()` — o esvaziamento que o arquivo temporário dava de graça.
- Custo aceito: os testes passam a exigir internet. O pipeline que eles testam
  também exige; e o guard-rail de nome (`_teste` na própria URL) protege a
  produção.
- `tests/test_mcp_server.py` segue como cliente **stdio** (o servidor local
  continua existindo — seção 4.1) contra a base real já populada, como hoje.

## 4. NI-20 — MCP remoto (HTTP)

### 4.1 Transporte

O `mcp_server.py` ganha o transporte **streamable HTTP** do FastMCP em modo
**stateless** (`stateless_http=True` — sem sessão persistida, o que casa com
serverless que escala a zero). O stdio **continua sendo o default** (`python
src/mcp_server.py`), para depuração e para o `test_mcp_server.py`; uma flag
`--http` (porta via `PORT`, convenção dos hosts) liga o modo remoto. As tools
não mudam: continuam finas sobre `consulta.py`, que agora lê o Neon.

Bônus já conhecido do dogfooding: no stdio, mudou código = reconectar o
cliente; no remoto, o deploy resolve.

### 4.2 Proteção: prefixo de rota secreto

Auth de verdade é Fase 1 (NI-11). Na 0b, o app HTTP é montado sob um prefixo
vindo de `MCP_SEGREDO` (`https://<host>/<segredo>/mcp`); qualquer rota fora
dele responde 404. Segredo na URL porque é o que os apps de agente aceitam
hoje para connector custom sem OAuth — e a URL não é divulgada (risco aceito
no PRD §8). Trocar o segredo = trocar a env e reconectar o connector.

### 4.3 Host serverless

Critérios: free tier **sem cartão** (PRD §7: "nada de cloud paga"), Python
ASGI, deploy simples, cold start tolerável para "primeira pergunta às 21h".

1. **Vercel (primeira tentativa):** hobby tier sem cartão, runtime Python com
   ASGI, deploy por git push. Risco a smoke-testar: o streamable HTTP do
   FastMCP sobre o runtime Python deles.
2. **Cloud Run (fallback):** container = zero surpresa de runtime e free tier
   folgado, mas exige cartão no billing — só se a Vercel falhar no smoke test.
3. Render free descartado: cold start de ~1 min depois do sleep conflita
   diretamente com o momento de uso ("na rua, à noite").

A decisão final é da implementação (etapa 5), com este ranking. O deploy leva
`EVENTOS_DB_URL` (pooled) e `MCP_SEGREDO` como env vars do host.

### 4.4 Connector no celular

Plugar a URL secreta como connector custom no app do agente que o autor usa no
celular. `docs/TESTE_MCP.md` ganha a seção do connector remoto; as configs
stdio existentes continuam válidas (agora lendo o Neon — o `.mcp.json` local
precisa da env `EVENTOS_DB_URL` visível para o processo).

## 5. Operação

- **Primeira carga:** criar projeto Neon (free, sem cartão) com os bancos
  `eventos` e `eventos_teste`; setar `EVENTOS_DB_URL` no PC; rodar
  `python src/atualizar.py --precificar-tudo`. O relatório e a tabela
  `execucoes` funcionam como hoje.
- **Cadência:** segue sob demanda, na mão (ex.: 9h de sexta serve o autor às
  21h com o PC desligado). GitHub Actions é Fase 1 (NI-10) — e, como o destino
  já é a base remota, o NI-10 vira só a troca de quem dispara.
- **Latência aceita (PRD §8):** Neon free hiberna após inatividade (~alguns
  segundos de wake na primeira consulta da noite) + cold start do serverless.
  Aceitável para um usuário; medir antes de prometer a terceiros.
- **Sem dado a migrar:** a base é descartável por convenção — nasce vazia no
  Neon e re-raspa. O histórico de `execucoes` local se perde (irrelevante).

## 6. Fora de escopo (deliberado)

- **GitHub Actions** (NI-10) e **auth de verdade + instrumentação** (NI-11) —
  Fase 1.
- **Backend duplo SQLite/Postgres** — complexidade permanente para transição
  de dias.
- **Pool/cache de conexão no read-path, jsonb, setweight no FTS, migrações de
  schema formais** — otimizações sem dor medida; base segue descartável.
- **Porta B** (páginas públicas JSON-LD) — Fase 2, mesmo já havendo serverless.

## 7. Plano de teste / critério de aceite

- Os 4 scripts de `tests/` passam contra `eventos_teste` no Neon.
- **Paridade de consulta:** rodada real (`--sem-shotgun` ao menos) gravando no
  Neon; `python src/consulta.py` compara as consultas canônicas com o
  comportamento pré-migração ("pagode", "funk OR techno", "eletrônica"
  com/sem acento, futuros sem vazamento de passados).
- `test_mcp_server.py` (stdio) passa contra a base real no Neon.
- Smoke HTTP local: `python src/mcp_server.py --http` + cliente MCP de teste
  apontando para `http://localhost:<porta>/<segredo>/mcp`.
- Deploy: mesma verificação contra a URL pública; rota sem o segredo → 404.
- **Critério da fase (PRD §6):** o autor, fora de casa e com o computador
  desligado, pergunta ao agente "o que tem hoje em Brasília" pelo celular — e
  confia na resposta em vez de abrir o Sympla.

## 8. Ordem de implementação

1. **Neon:** projeto + bancos + env vars locais.
2. **Migração do dialeto** (seção 2): `sql/*.sql` reescritos, store/consulta/
   derivar/enriquecer/atualizar/demo portados, normalização de datas no upsert.
3. **Testes portados** (seção 3) + rodada real no Neon + paridade de consulta.
4. **MCP remoto local** (seções 4.1–4.2): transporte HTTP + prefixo secreto,
   smoke local.
5. **Deploy** (seção 4.3) + connector no celular (4.4).
6. **Docs:** CLAUDE.md (comandos, arquitetura, convenção de base descartável,
   env vars), TESTE_MCP.md (connector remoto), backlog (NI-09/NI-20 saem ao
   concluir; nota no NI-10).
