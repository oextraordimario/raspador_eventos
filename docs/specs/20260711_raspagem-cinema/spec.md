# Spec — Raspagem de cinema: o que está passando em Brasília (NI-07)

> **Status:** especificada em 2026-07-11 a partir do spike `spikes/cinema/`
> (validado no mesmo dia: 38 filmes, 1.232 sessões, 8/8 cinemas). **O quê/por
> quê:** PRD §2/§6 — mesmo problema de fundo das festas (dados espalhados, busca
> ruim), dogfoodável pelo autor: *"o que está passando nos cinemas de Brasília
> essa semana?"*. Implementação pendente.
>
> **Dependência:** a base migrou para Postgres/Neon (Fase 0b,
> `docs/specs/20260711_consulta-na-nuvem/`). Esta spec assume o schema pós-
> migração; o DDL abaixo segue as convenções que `sql/schema.sql` tiver na hora
> de implementar.

---

## 1. Descoberta que destrava o NI-07 (spike de 2026-07-11)

**Um scraper determinístico cobre os 8 cinemas-alvo — sem navegador, sem auth.**
Todos vendem via Ingresso.com, e a API de conteúdo deles é aberta:

```
GET https://api-content.ingresso.com/v0/sessions/city/12/theater/{id}?date=YYYY-MM-DD
```

Devolve, por cinema×dia: filme (título, gêneros, duração, classificação
indicativa, distribuidora, pôster, trailer, tags tipo "Férias escolares") e
sessões por sala (horário local ISO com offset `-03:00`, tipos
2D/3D/XD/VIP/DUB/LEG, preço, link de checkout). cityId de Brasília = **12**.

| Cinema (apelido canônico) | theaterId | Obs. |
|---|---|---|
| Cinemark Iguatemi | 847 | |
| Cinemark Pier 21 | 128 | |
| Kinoplex ParkShopping | 124 | |
| Kinoplex Pátio Brasil | 126 | |
| Kinoplex Boulevard | 833 | |
| Cinesystem CasaPark | 1605 | nome na API: "Cinesystem Caixa Brasília" (naming rights) |
| Cine Brasília | 1583 | fecha alguns dias — API devolve **404** = sem sessão |
| Cine Cultura Liberty Mall | 1538 | |

Fatos que moldam o design (medidos no spike):

- **404 = dia sem programação**, não erro. Tratar como lista vazia.
- **A programação vira na quinta**: além da próxima quarta só há pré-vendas
  (`inPreSale`). Raspar 8 dias corridos (hoje → +7) cobre a semana útil.
- **Sessão de cinema não tem id nativo estável entre semanas** (confirmando o
  backlog): `sessionId` só vale dentro da grade corrente. Já o **id do filme é
  estável** (ex.: `28256` = Toy Story 5).
- Checkout de Cinesystem/Kinoplex aponta para `checkout.ingresso.com` — as
  redes são clientes da Ingresso.com na venda; a fonte primária é a infra de
  venda delas, não um agregador de segunda mão.
- Fallbacks por rede auditados e documentados em `spikes/cinema/README.md`
  (Kinoplex PHP+JSON, Cinesystem site-api JSON, Cinemark RSC via HTTP puro,
  independentes em WordPress). **Não implementar agora** — só se a primária
  quebrar; o detector de queda do relatório de saúde avisa.

## 2. Design

### 2.1 Modelagem: domínio próprio, arquitetura espelhada

Sessão de cinema NÃO entra na tabela `eventos`: são ~1.2k linhas/semana
voláteis, sem id estável, que poluiriam FTS, dedupe, `sumido` e relatório.
Em vez disso, o domínio cinema **espelha a arquitetura** Bronze → Prata →
consulta → MCP com tabelas próprias:

```sql
-- Bronze: payload bruto por cinema×dia, substituído a cada rodada
CREATE TABLE IF NOT EXISTS cinema_raw (
  cinema_id  TEXT NOT NULL,      -- theaterId da Ingresso.com
  dia        DATE NOT NULL,
  payload    JSONB NOT NULL,     -- resposta crua do endpoint
  raspado_em TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (cinema_id, dia)
);

-- Prata: derivada 100% de cinema_raw, a seco (derivar_cinema)
CREATE TABLE IF NOT EXISTS filmes (
  id            TEXT PRIMARY KEY,  -- id do filme na Ingresso.com (estável)
  titulo        TEXT NOT NULL,
  generos       TEXT,              -- "Animação, Aventura" (mesmo estilo de eventos.categoria)
  duracao_min   INTEGER,
  classificacao TEXT,
  distribuidora TEXT,
  url           TEXT,              -- página do filme na Ingresso.com
  poster        TEXT,
  trailer       TEXT,
  em_pre_venda  BOOLEAN DEFAULT FALSE,
  raspado_em    TIMESTAMPTZ,
  busca         tsvector           -- título + gêneros, config 'pt' (igual eventos)
);

CREATE TABLE IF NOT EXISTS sessoes (
  id         TEXT PRIMARY KEY,     -- sessionId (estável só dentro da grade)
  filme_id   TEXT NOT NULL REFERENCES filmes(id) ON DELETE CASCADE,
  cinema     TEXT NOT NULL,        -- apelido canônico da tabela da §1
  cinema_id  TEXT NOT NULL,
  inicio     TIMESTAMPTZ NOT NULL, -- parse via tempo.instante (offset -03:00)
  sala       TEXT,
  tipos      TEXT,                 -- "3D/XD/Dublado" — cru, quem interpreta é o agente
  preco      NUMERIC,
  url_compra TEXT
);
CREATE INDEX IF NOT EXISTS sessoes_inicio_idx ON sessoes (inicio);
```

**Estratégia de escrita: snapshot, não upsert.** A grade é substituída inteira
a cada rodada: o passo de raspagem faz replace de `cinema_raw` (PK
cinema_id+dia); a derivação **trunca `sessoes` e reconstrói filmes+sessoes** a
partir de `cinema_raw`. Idempotente como `derivar.py`/`enriquecer.py`: campo
novo do payload = função na derivação + re-derivar, sem re-raspar. Sem dedupe
(fonte única) e sem `sumido` (sessão que saiu da grade simplesmente não é
reinserida).

Decisões herdadas da filosofia do projeto:

- Sessões especiais ("Cine Inclusivo", "Sessão Azul", "Cine Pets") chegam como
  tipo da sessão e **ficam cruas em `tipos`** — quem interpreta é o agente,
  não regex (mesma regra dos lotes NI-18).
- "Sessão Atípica: Toy Story 5" vem como filme separado (id próprio) — deixar
  como está; o título já se explica.

### 2.2 Scraper: `src/scrapers/cinema.py`

Contrato próprio (difere dos scrapers de eventos — devolve grade, não lista de
eventos): `raspar(dias=8)` → `{"raw": [(cinema_id, dia, payload)], "erros": [...]}`.

- Loop cinemas (§1) × dias (hoje → +N-1), `time.sleep(0.3)` entre chamadas
  (~64 requisições ≈ 40 s).
- 404 → dia sem sessão (não conta como erro). Erro de rede/HTTP ≠ 404 →
  registra em `erros` e **preserva o payload anterior daquele cinema×dia**
  (não substitui a Bronze com buraco).
- Preenche `ULTIMA_RASPAGEM` com `coletados` (cinemas que responderam ≥1 dia)
  e `total_site` (8) — plugando no medidor de cobertura do `atualizar.py`.

### 2.3 Pipeline: novo passo no `atualizar.py`

`raspar cinema → replace cinema_raw → derivar_cinema (trunca e reconstrói
filmes/sessoes) → tsvector de filmes → relatório`.

- Roda por default; `--sem-cinema` pula (simetria com `--sem-shotgun`).
- `--so-derivar` também re-deriva o cinema a partir de `cinema_raw`.
- Relatório de saúde: linha "cinema: X filmes, Y sessões em Z/8 cinemas" +
  alerta de queda >50% vs. rodada anterior (mesmo detector das festas).
- `execucoes`: o passo entra na rodada com erros por cinema×dia.

### 2.4 Consulta e MCP

`src/consulta.py` ganha a camada canônica do cinema; `mcp_server.py` expõe
tools finas por cima (padrão `buscar_eventos`/`detalhar_evento`):

- `buscar_filmes(texto?, data_inicio?, data_fim?, cinema?, limite?)` → lista de
  filmes com agregado por filme: gêneros, duração, classificação, cinemas em
  exibição, nº de sessões na janela, url. Busca textual pela coluna `busca`
  (título+gêneros, unaccent+stem pt — "animacao" acha "Animação").
- `sessoes_filme(titulo_ou_id, data_inicio?, data_fim?, cinema?)` → sessões
  detalhadas (cinema, dia, hora, sala, tipos, preço, link de compra) de UM
  filme. Análogo do `detalhar_evento`.
- `data_atual` (existente) já dá "hoje"/"fim de semana" para os filtros.
- Sessões passadas somem por default (`inicio >= agora`).

## 3. Fora de escopo

- **Cinépolis / Taguatinga** (cityId 113): fora da lista do usuário.
- **Fallbacks por rede**: auditados no spike, implementação só se a fonte
  primária quebrar.
- **Unificação com `eventos`**: filme não vira evento; se um dia o agente
  precisar de busca única, é camada de cima (tool que consulta os dois).
- Enriquecimento por LLM, notas/reviews, meia-entrada/regras de preço por
  assento, histórico de grades (a Bronze guarda só a última por cinema×dia).

## 4. Plano de teste

- `tests/test_cinema.py` (base descartável `eventos_teste`, padrão
  `base_teste.py`): payload de amostra do spike (`capturas/amostra_raw.json`)
  → derivação de filmes/sessoes (títulos, tipos compostos "3D/XD/Dublado",
  preço, timezone do `inicio`), 404 tratado como vazio, snapshot substitui
  grade anterior sem duplicar, sessão passada escondida na consulta,
  `buscar_filmes("eletrônica"-style: "animacao")` achando por gênero.
- Rodada real: `python src/atualizar.py --sem-shotgun` + conferir relatório
  (8/8 cinemas) + `tests/test_mcp_server.py` estendido com as duas tools novas.

## 5. Riscos e casos de borda

| Risco | Mitigação |
|---|---|
| Ingresso.com muda/fecha a API | Detector de queda no relatório + fallbacks por rede já mapeados (`spikes/cinema/README.md`) |
| Cinema sai da Ingresso.com (troca de bilheteira) | Cobertura Z/8 no relatório denuncia; fallback da rede cobre |
| Grade vazia na quinta de manhã (virada) | Snapshot preserva payload anterior em erro; grade legitimamente menor não é erro — alerta só em queda >50% |
| `duration`/`price` ausentes ou nulos | Colunas anuláveis; agente lida com null (mesma convenção do preco_min) |
| Filme em 2 cidades/ids (raro) | Chave é o id da Ingresso.com; título repetido não colide |
