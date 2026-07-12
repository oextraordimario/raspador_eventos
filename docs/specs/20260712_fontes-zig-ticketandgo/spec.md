# Spec — Fontes novas: Zig e Ticket and Go (NI-22)

> **Status:** especificada e IMPLEMENTADA em 2026-07-12, a partir do spike
> `spikes/zig-ticketandgo/` (validado no mesmo dia: Zig 3 eventos DF de 252 no
> catálogo nacional; Ticket and Go 102 eventos DF de 462). **O quê/por quê:**
> pedido direto do usuário — duas plataformas de ingresso adicionais para o
> recorte de Brasília. Mais fontes = mais recall na hipótese de risco central
> (a raspagem). Testes: `tests/test_zig_ticketandgo.py`.
>
> **Contexto de infra:** eventos das duas fontes entram na tabela `eventos`
> existente (schema unificado, **sem mudança de DDL** — não precisa descartar a
> base). Datas normalizadas na escrita pelo `upsert_eventos` (`tempo.norm_ts`),
> payload bruto na Bronze (`eventos_raw`), lotes na Prata (`lotes`), como as
> fontes atuais.

---

## 1. Descoberta que destrava o NI-22 (spike de 2026-07-12)

**As duas fontes são raspáveis por API JSON, sem navegador e sem auth** —
mesma classe de Sympla/Ingresse. Detalhes completos e capturas de referência
em `spikes/zig-ticketandgo/README.md`; o que molda o design:

### Zig (`ticket-api.superticket.com.br` — API do SuperTicket, incorporado pela Zig)

```
GET /events?per_page=50&page=N          # catálogo NACIONAL paginado (meta.last_page)
GET /events/{slug}                      # detalhe: description HTML, event_location.name
GET /events/{id}/tickets                # respondeu VAZIO em todos os testes
```

- **Sem filtro server-side de estado** — paginar as ~6 páginas e filtrar
  `event_location.state == "DF"` do lado de cá (catálogo nacional ~250).
- Datas ISO com offset local (`-03:00`); `event_location.city` às vezes vem
  com espaço na frente — trim.
- `event_location.neighborhood` existe no catálogo → derivação de `bairro`.
- URL pública: `https://zig.tickets/eventos/{slug}`.

### Ticket and Go (`production-api-v1-service.ticketandgo.com.br`)

```
POST /eventos/pesquisa  {"pesquisa": ""}   # catálogo INTEIRO (~460 eventos, ~3,4 MB)
GET  /eventos/{slug}                       # bilhetes (lotes) + sessoes + taxa_conveniencia
```

- O catálogo **já traz a descrição HTML completa** de cada evento — a fonte
  não precisa do passo "descrever" (como o Shotgun).
- **cidade/estado/cep vêm NULOS**; o local mora nos textos `local` e
  `endereco_completo`. Filtro DF textual (§2.2); cidade/estado ROTULADOS pelo
  filtro (precedente: Shotgun rotula pela cidade pesquisada).
- Datas separadas e sem fuso: `inicio` "YYYY-MM-DD" + `hora_incio` "HH:MM:SS"
  (typo da fonte, sem o segundo "i") = hora local de Brasília → compor
  `YYYY-MM-DDTHH:MM:SS-03:00` no scraper; o upsert normaliza para UTC.
- `taxa_conveniencia` é FRAÇÃO (0.1 = 10%) sobre o valor do bilhete.
- URL pública: `https://www.ticketandgo.com.br/evento/{slug}`.

## 2. Design

### 2.1 Scrapers: mesmo contrato dos existentes

`src/scrapers/zig.py` e `src/scrapers/ticketandgo.py`, cada um com
`raspar(...)` → lista de dicts normalizados (`_normalizar(...)`), `_futuro`
local, `ULTIMA_RASPAGEM` com `coletados`/`total_site` ao fim.

- **`total_site` = nº de eventos DF identificados no catálogo** (não o total
  nacional — o medidor de cobertura mede o recorte, e "3/252" leria como
  scraper quebrado). `coletados` = futuros normalizados.
- Zig: `raspar(estado="DF")` pagina até `meta.last_page` (teto de segurança
  `max_paginas=12`, o dobro do observado) e filtra por estado.
  `raspar_descricao(slug)` → `{"descricao", "nome", "payload"}` (HTML limpo
  pelo mesmo `_limpar_html` de Sympla/Ingresse; devolve `nome` para a guarda
  uniforme de nome do `_descrever` — barata, mesmo sem namespace ambíguo
  conhecido tipo Bileto/NI-17). `raspar_tickets(slug)` (NI-23, resolvido no
  mesmo dia): a página pública é SSR e embute o payload de tickets no
  `__NEXT_DATA__` (`pageProps.tickets`) — lê de lá por HTTP puro, sem
  navegador, e devolve também o `nome` da página para a guarda do
  `_precificar`. O endpoint JSON `/events/{id}/tickets` segue respondendo
  vazio sem códigos opcionais do front (`d`/`s` — cupom/vendedor); a página
  dispensa mapeá-los. Nota: o `json_ld` da página TEM offers, mas com preços
  ERRADOS (bug da fonte: mistura os percentuais de desconto do
  `event_sectors` com preço) — não usar; `pageProps.tickets` é o que a UI
  renderiza. O `event_sectors` do detalhe ficou decifrado de tabela:
  `price × (1 − discount/100)` = o `value` real do ingresso.
- Ticket and Go: `raspar()` faz o POST de pesquisa vazia e filtra DF.
  Normaliza `descricao` direto do catálogo (HTML → texto). `raspar_tickets(slug)`
  → `{"payload"}` = o `data` do detalhe (bilhetes + sessoes + taxa), para o
  passo precificar.

### 2.2 Filtro DF do Ticket and Go (textual, calibrado no spike)

`local + " " + endereco_completo` contém, em qualquer posição:
`"brasília"` (casefold) **OU** `\bDF\b` **OU** CEP `\b7[0-3]\d{3}-?\d{3}\b`
(faixa 70000–73999 = DF). Os 102 eventos DF do catálogo de 2026-07-12 passam;
Curitiba/SP/etc. não. Falso negativo possível (endereço sem nenhuma das três
marcas) é aceitável: erro para o lado de perder, não de poluir outra cidade.

### 2.3 Pipeline (`atualizar.py`)

- `_raspar`: duas entradas novas na lista de fontes (tolerância a falha por
  fonte já cobre). `sumido` funciona de graça (âncora `raspado_em`).
- `_descrever`: passa a incluir `zig` (branch por slug no fim da URL, guarda
  `_mesmo_nome` como no Sympla). Ticket and Go NÃO entra (descrição já vem no
  catálogo; o COALESCE do upsert a preserva).
- `_precificar`: passa a incluir `ticketandgo` e `zig` (slug da URL →
  `raspar_tickets`), dentro da mesma janela de 30 dias. No Zig o payload só
  entra na Bronze se o nome da página bater com o da base (`_mesmo_nome`).
- Relatório/`execucoes`: nada a fazer — fontes novas aparecem sozinhas
  (dicts por fonte, comparação vs. rodada anterior idem).

### 2.4 Derivação (`derivar.py`)

- `("zig", "catalogo")` → `bairro` (= `event_location.neighborhood`, trim).
- `("zig", "tickets")` → lotes do `pageProps.tickets` (NI-23): para cada
  ticket público de `tickets[] + unavailables[]`, `preco = value + fee`
  (fee é a taxa separada, ~12%), `gratis = preco == 0`, `esgotado = 1` se o
  id está em `unavailables`. O nome já embute setor e condição ("Geral
  [Adulto - Meia Entrada] Individual"); `sector_name` só prefixa quando o
  nome não o traz.
- `("ticketandgo", "tickets")` → lotes: vêm em `bilhetes[]` (evento simples)
  **OU aninhados em `setores[].bilhetes[]`** (evento com setor — achado na
  primeira rodada real: 26/37 payloads só tinham setores; o nome do lote vira
  "setor — lote", como no Ingresse). Para cada bilhete:
  `valor = float(valor_bilhete)`, `taxa = round(valor × taxa_conveniencia, 2)`
  (None se a fonte não informar a fração), **`preco = valor + taxa`** (invariante
  da tabela: total a pagar), `gratis = preco == 0`, `esgotado = 0` (a fonte só
  lista lote à venda — sem flag de esgotado no payload). Agregação
  `preco_min`/`tem_gratis`/`esgotado` já existente cobre.

### 2.5 Enriquecimento e consulta

- `enriquecer._PREF_FONTE` ganha `zig: 3, ticketandgo: 4` (desempate do
  canônico no dedupe cross-fonte; Sympla/Shotgun/Ingresse seguem na frente por
  completude de dados já conhecida).
- `consulta.py`/`mcp_server.py`: **zero mudança** — são agnósticos de fonte;
  `outras_urls` do dedupe passa a poder apontar para as fontes novas de graça.

## 3. Fora de escopo

- ~~**Preço/lotes do Zig**~~ — ficou fora do v1 (endpoint de tickets vazio,
  `event_sectors` ambíguo), virou o **NI-23** a pedido do usuário e foi
  **resolvido no mesmo dia** via `__NEXT_DATA__` da página pública (§2.1/§2.4).
- **Ruído de teste do Ticket and Go** ("Tarifa top" com fim em 2040, "teste
  jp"): política de ruído existente (enriquecer v1 / NI-04), não é papel do
  scraper. Se poluir o dogfooding, vira termo novo no filtro v1.
- **Sessões múltiplas do Ticket and Go** (`sessoes[]` no detalhe): o payload
  fica na Bronze; modelar sessão-por-linha só se aparecer caso real (hoje os
  eventos DF são de sessão única — dias distintos já viram eventos distintos
  no catálogo, ex.: Trust Love 12/07, 14/07...).
- **Outras cidades**: recorte do PRD continua Brasília.

## 4. Plano de teste

`tests/test_zig_ticketandgo.py` (banco descartável `eventos_teste`, padrão
`base_teste.py`), com payloads de amostra do spike:

- Normalização Zig: id `zig:{id}`, trim de cidade, URL pública, bairro
  derivado de neighborhood; filtro por estado.
- Normalização Ticket and Go: composição de data local → UTC na escrita
  (`2026-08-29 19:00 -03:00` → `2026-08-29T22:00:00+00:00` na base), cidade
  rotulada, descrição limpa de HTML, filtro DF textual (casos reais + 
  contraexemplo de outra cidade).
- Lotes Ticket and Go: valor 60 + taxa 10% → `preco 66.0/taxa 6.0`;
  bilhete de valor 0 → `gratis`; agregação `preco_min` e `detalhar_evento`.
- Rodada real: `python src/atualizar.py --sem-shotgun` + conferir no relatório
  as duas fontes novas com coleta > 0.

## 5. Riscos e casos de borda

| Risco | Mitigação |
|---|---|
| API do SuperTicket sai do ar quando a Zig migrar de vez | Detector de queda >50% no relatório; catálogo DF hoje é pequeno (3), perda contida |
| Pesquisa vazia do TNG deixar de devolver o catálogo | Mesmo detector; fallback mapeado: `pesquisa` por termos ("df", "brasília") devolve até 100 cada |
| Catálogo nacional do Zig crescer muito (paginação cara) | Teto `max_paginas`; log de páginas; reavaliar filtro server-side se surgir |
| Filtro DF textual do TNG errar | Erra para o lado de PERDER evento (não polui); casos reais no teste seguram regressão |
| `taxa_conveniencia` mudar de fração para valor absoluto | Teste com payload real trava a semântica; derivação a seco = corrigir função + `--so-derivar`, sem re-raspar |
| Evento TNG sem `hora_incio` | Compor com `00:00:00` (só a data já serve ao filtro por dia) |
