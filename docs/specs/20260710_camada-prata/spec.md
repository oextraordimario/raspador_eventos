# Spec — Camada Prata: preço, esgotado, cancelado e popularidade no MCP

> **Status:** especificada e implementada em 2026-07-10, na sequência da Bronze
> (`docs/specs/20260710_camada-bronze/spec.md`). **O quê/por quê:** a tabela
> `eventos` é a camada Prata (consultável); ela ganhou a Bronze mas seguia sem
> os campos que faltavam ao agente — sobretudo **preço** (NI-12, crítico:
> sem preço o agente não ajuda a decidir). Esta spec fecha o ciclo
> Bronze → Prata → consulta → MCP.

---

## 1. Descoberta que destrava o NI-12 (medida em 2026-07-10)

O preço **não está** nos payloads de catálogo/detalhe (confirmado no spike da
Bronze) — mas as duas fontes têm endpoints de tickets abertos:

- **Sympla:** `GET event-page.svc.sympla.com.br/api/event-bff/purchase/event/{id}/tickets`
  (mesmo id de página do "descrever"). Traz lotes com
  `salePriceWithDiscountMonetary.decimal` (R$), `isFree`, `status`,
  `currentAvailableQty` — preço, gratuidade e lotação de uma vez.
- **Ingresse:** `GET api-embedstore.ingresse.com/api/v1/event/{id}/session/{sid}/tickets`
  (apikey pública embutida no embed de checkout do próprio site; sessões via
  `GET event.ingresse.com/public/{id}`, sem chave). Eventos "passaporte" usam
  `session/passports/tickets` — fallback quando a sessão vem vazia. Traz
  `type[].price` (R$), `tax`, `status` por lote.
- **Shotgun:** já tínhamos — `offers[]` no JSON-LD (Bronze `catalogo`).

## 2. Design

### 2.1 Novo passo "precificar" no `atualizar.py`

Busca o payload de tickets de Sympla/Ingresse e grava na Bronze como
`origem='tickets'`. **Não é incremental** (preço/lote é volátil — muda entre
rodadas): refetch de todos os eventos futuros a cada atualização
(~240 requisições ≈ 2 min; aceito na Fase 0 sob demanda). Regras:

- Sympla: só eventos com `descricao IS NOT NULL` — ou seja, que **passaram na
  guarda de nome do NI-17** (o endpoint de tickets não devolve nome para
  validar; sem essa âncora, id trocado traria preço alheio). URLs bileto.*
  continuam fora. Custo: ~12 eventos sem descrição ficam sem preço — corretude
  vale mais que essa cobertura.
- Ingresse: `raspar_tickets(id)` resolve as sessões sozinho (endpoint público)
  e tenta `session/{primeira}/tickets` → fallback `passports`.
- Shotgun: nada a buscar (offers já estão na Bronze).

### 2.2 Derivações novas (`src/derivar.py`)

| coluna (nova no schema) | fonte, origem | regra |
|---|---|---|
| `preco_min` (já existia) | sympla, tickets | mín. de `salePriceWithDiscountMonetary.decimal` dos lotes visíveis; `isFree` → 0 |
| | ingresse, tickets | mín. de `type[].price` não-ocultos |
| | shotgun, catalogo | mín. de `offers[].lowPrice/price` (a mesma regra do scraper, agora derivada) |
| `esgotado` 0/1 | sympla, tickets | todos os lotes visíveis com `currentAvailableQty = 0` |
| | ingresse, tickets | todos os lotes com `status = 'finished'` |
| | shotgun, catalogo | todas as `offers` com availability `SoldOut` |
| `cancelado` 0/1 | sympla, detalhe | campo `cancelled` do BFF |
| | shotgun, catalogo | `eventStatus` ≠ `EventScheduled` |
| `popularidade` | sympla, catalogo | `global_score` (trending do Sympla — dá ranking) |
| `bairro` (já existia) | sympla, catalogo | `location.neighborhood` |

`preco_min` passa a ser **coluna derivada** (a derivação é a palavra final;
o upsert do Shotgun continua escrevendo o valor, inofensivo). Derivações do
mesmo evento nunca disputam coluna: catalogo → bairro/popularidade/…,
detalhe → cancelado, tickets → preco_min/esgotado.

### 2.3 Exposição na consulta e no MCP

- `consulta.buscar_eventos`: `CAMPOS` ganha `bairro`, `esgotado` e
  `popularidade`. **Evento cancelado some por padrão** (junto do ruído;
  `incluir_ruido=True` devolve). Esgotado NÃO some — "está esgotado" é
  resposta útil.
- `mcp_server.buscar_eventos`: docstring atualizada (preço em R$; 0 = grátis;
  null = fonte não informou; esgotado 1 = sem ingressos; cancelados já
  filtrados).

## 3. Fora de escopo

Ranking por popularidade na ordenação (segue por data), tool `detalhar_evento`
(NI-13), TTL/refresh incremental de campos voláteis (NI-15 formaliza), preço
dos ~12 Sympla sem descrição validada.

## 4. Plano de teste

- `tests/test_bronze.py` estendido: derivação de preco_min/esgotado/cancelado/
  popularidade a partir de payloads de tickets/detalhe/JSON-LD de exemplo,
  cancelado escondido na consulta por padrão, esgotado exposto.
- Pipeline completo real + `tests/test_mcp_server.py` (cliente MCP de verdade)
  com conferência de preço preenchido por fonte no relatório de saúde.
