# Spike: raspagem do Zig e do Ticket and Go (NI-22)

Teste exploratório para responder: **dá pra raspar deterministicamente os
eventos de Brasília no Zig (zig.tickets) e no Ticket and Go
(ticketandgo.com.br)?** (pedido do usuário em 2026-07-12, backlog NI-22)

Objetivo do spike — para cada plataforma:

1. Mapear a técnica: API JSON interna? HTML estático? Precisa de navegador (Playwright)?
2. Escrever um probe determinístico que devolva os eventos do DF normalizáveis.
3. Anotar achados aqui para virar spec em `docs/specs/` depois.

## Achados (2026-07-12)

**Veredito: as duas fontes são raspáveis por API JSON, sem navegador e sem
auth** — mesma classe de dificuldade de Sympla/Ingresse, mais fáceis que o
Shotgun. Rodada de teste: Zig 3 eventos DF (de 252 no catálogo nacional),
Ticket and Go 102 eventos DF (de 462).

### Zig (zig.tickets)

Site Next.js; o front consome a API do **SuperTicket** (plataforma que a Zig
incorporou — os assets vêm de `assets.superticket.com.br`):

- Catálogo: `GET https://ticket-api.superticket.com.br/events?per_page=50&page=N`
  → `{"data": [...], "meta": {total, last_page, ...}}`. **Sem filtro
  server-side de estado** (`by_state`/`uf`/`state` são ignorados;
  `order_by_state=DF` só reordena). O catálogo nacional é pequeno (~250
  eventos, 6 páginas de 50): paginar tudo e filtrar
  `event_location.state == "DF"` do lado de cá.
- Catálogo traz: `name`, `slug`, `start_date`/`end_date` (ISO local `-03:00`),
  `event_location` (city/state/**neighborhood**/formatted_address), banner.
  `event_location.city` às vezes vem com espaço na frente (`" Brasília"`) — trim.
- Detalhe: `GET /events/{slug}` → `description` (HTML), `event_location.name`
  (nome do local, ex.: "ARENA CONIC"), `producer`, `event_sectors`.
- Tickets: `GET /events/{id}/tickets` respondeu **vazio** em todos os testes
  (mesmo em evento à venda) — o front manda params de sessão (`d`/`s`) que não
  mapeamos; `event_sectors` tem preço mas com semântica ambígua (inteiros tipo
  `1000`, "discounts" percentuais, sem nome de lote). **Preço do Zig fica fora
  do v1** (preco_min NULL = "fonte não informou", convenção já existente).
- URL pública: `https://zig.tickets/eventos/{slug}` (confirmado por HTTP 200).

### Ticket and Go (ticketandgo.com.br)

SPA Vue/Vite atrás de queue-it (como o Ingresse); a API de leitura é aberta:

- Catálogo: `POST https://production-api-v1-service.ticketandgo.com.br/eventos/pesquisa`
  body `{"pesquisa": ""}` → **catálogo inteiro** (~460 eventos, ~3,4 MB), cada
  evento **já com a descrição HTML completa** — não precisa do passo
  "descrever" (como o Shotgun). O `GET /eventos/todos/lista` visto no bundle
  responde 404 (a rota colide com `/eventos/{slug}`); a pesquisa vazia cobre.
- **cidade/estado/cep vêm NULOS** no catálogo; o local mora nos textos `local`
  e `endereco_completo` ("SCTN - Plano Piloto, Brasília - DF, 70040-010").
  Filtro DF textual: "brasília" (casefold) OU `\bDF\b` OU CEP `7[0-3]xxx-xxx`
  nesses campos. Cidade/estado são ROTULADOS pelo filtro (como no Shotgun).
- Datas separadas: `inicio`/`fim` = "YYYY-MM-DD", `hora_incio`/`hora_fim` =
  "HH:MM:SS" (sim, `hora_incio` sem o segundo "i" — typo da fonte). Sem fuso:
  é hora local de Brasília → compor "YYYY-MM-DDTHH:MM:SS-03:00".
- Detalhe/tickets: `GET /eventos/{slug}` → `bilhetes` (lotes com `nome` +
  `valor_bilhete`) e `sessoes`. Evento COM setor não tem `bilhetes` no topo:
  os lotes vêm aninhados em `setores[].bilhetes[]` (achado na primeira rodada
  real — 26/37 payloads eram assim). `taxa_conveniencia` é FRAÇÃO sobre o
  valor (0.1 = 10%): total a pagar = valor × (1 + taxa), seguindo a convenção
  "preco = total com taxa" da tabela lotes. Bilhete esgotado não tem flag
  visível — assumimos que a fonte só lista lote à venda (esgotado=0).
- Ruído conhecido: o catálogo tem eventos de teste da própria plataforma
  ("Tarifa top" com fim em 2040, "teste jp", "evento gratuito") — tratados
  pela política de ruído existente (enriquecer v1 / NI-04), não pelo scraper.
- URL pública: `https://www.ticketandgo.com.br/evento/{slug}`.

## Estrutura

- `probe_zig.py` — pagina o catálogo, filtra DF, detalha um evento
- `probe_ticketandgo.py` — catálogo via pesquisa vazia, filtra DF, detalha um evento
- `capturas/zig_catalogo_df.json` / `capturas/tng_catalogo_df.json` — eventos DF brutos
- `capturas/zig_detalhe.json` / `capturas/tng_detalhe.json` — um detalhe bruto (schema)

Modelagem e integração no pipeline ficam na spec:
`docs/specs/20260712_fontes-zig-ticketandgo/spec.md`.
