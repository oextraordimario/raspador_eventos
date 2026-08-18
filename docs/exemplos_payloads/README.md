# Exemplos de payload bruto (camada `cru`)

Um exemplar do que **cada fonte respondeu**, no formato dela, para cavucar sem
abrir a base. Nas cinco plataformas é o **mesmo evento** atravessando as
origens que existem para ela (`catalogo` → `detalhe` → `tickets`), que é o que
faz o arquivo ensinar: dá para seguir o preço do catálogo até o lote.

Estes arquivos são **snapshot regenerável**, não fonte da verdade. A fonte da
verdade é o schema `cru` no Neon — append-only, com histórico. Para regravar a
pasta inteira contra a base atual:

```bash
python src/ferramentas/exemplos_payloads.py
```

> **Dados mascarados.** E-mail, telefone, CPF e token são substituídos por
> valores fictícios antes de escrever o arquivo — a estrutura é fiel, esses
> valores não. O mascaramento é **por padrão do valor**, não por lista de
> campos: campo novo que a fonte passe a mandar já entra coberto. O que a fonte
> publica na própria página do evento (nome do organizador, razão social)
> **permanece** — não é o que a máscara existe para proteger.

<!-- TABELA GERADA - nao editar a mao -->

| arquivo | exemplar | origem | `api` (era do endpoint) | coletado |
|---|---|---|---|---|
| `sympla_catalogo.json` | `sympla:3541189` | `catalogo` | `discovery-bff` | 2026-08-14 |
| `sympla_detalhe.json` | `sympla:3541189` | `detalhe` | `event-page-bff` | 2026-08-14 |
| `sympla_tickets.json` | `sympla:3541189` | `tickets` | `event-page-bff-tickets` | 2026-08-14 |
| `ingresse_catalogo.json` | `ingresse:89753` | `catalogo` | `—` | 2026-07-28 |
| `ingresse_detalhe.json` | `ingresse:89753` | `detalhe` | `—` | 2026-07-27 |
| `ingresse_tickets.json` | `ingresse:89753` | `tickets` | `api-site-tickets` | 2026-08-14 |
| `zig_catalogo.json` | `zig:26851` | `catalogo` | `superticket-events` | 2026-08-14 |
| `zig_detalhe.json` | `zig:26851` | `detalhe` | `superticket-events` | 2026-08-14 |
| `zig_tickets.json` | `zig:26851` | `tickets` | `next-data` | 2026-08-14 |
| `shotgun_catalogo.json` | `shotgun:06-09-reputation-ensaios-da-anitta` | `catalogo` | `json-ld` | 2026-08-14 |
| `ticketandgo_catalogo.json` | `ticketandgo:55628` | `catalogo` | `v1-evento` | 2026-08-14 |
| `ticketandgo_tickets.json` | `ticketandgo:55628` | `tickets` | `v1-evento` | 2026-08-14 |
| `cinema_grade.json` | cinema `847`, dia 2026-08-14 | `grade` | `ingresso.com/sessions` | 2026-08-14 |
| `instagram_extracao.json` | @ordinariobar, post `DcCN7JCh8KC` | `extracao` | `monid/tikhub` | 2026-08-14 |
| `instagram_post.json` | @ordinariobar, post `DcCN7JCh8KC` | `post` | `monid/tikhub` | 2026-08-14 |
| `tmdb_busca.json` | filme `31944` | `busca` | `tmdb/search` | 2026-07-27 |

<!-- FIM DA TABELA GERADA -->

## Onde olhar primeiro

- **Preço e lotes** — é onde as quatro fontes menos se parecem, e onde mora
  quase toda a regra de `LOTES`: `sympla_tickets.json` → `tickets[]` (valor
  **já com taxa**; repare no lote com `isFree: true`, que colapsaria o
  `preco_min` se ele não exigisse lote PAGO); `ingresse_tickets.json` →
  `detail.responseData[]` (preço **sem** taxa, `tax` à parte);
  `zig_tickets.json` → `tickets[]` (vem do `__NEXT_DATA__` da página, não do
  endpoint JSON, que responde vazio);
  `ticketandgo_tickets.json` → `bilhetes[]` mais `taxa_conveniencia`, que é
  **fração** (0.1 = 10%), somada na derivação.
- **O que a fonte chama de categoria** — `sympla_catalogo.json` →
  `event_type` (`"NORMAL"`) e `shotgun_catalogo.json` → `@type`
  (`"MusicEvent"`). Os dois já foram gravados como `categoria` em algum
  momento, e os dois têm **um valor só** na base inteira: zero poder de
  distinção, e poluição do FTS, que indexa a coluna. Antes de mapear campo de
  fonte para `categoria`, conte os distintos.
- **Endereço e cidade** — `shotgun_catalogo.json` → `location`, onde
  `addressLocality` ora traz a cidade, ora o bairro; é por isso que a cidade é
  ROTULADA pelo parâmetro de busca em vez de lida do payload.
  `ticketandgo_catalogo.json` → `endereco`, hoje uma lista **vazia**, que é a
  razão de o filtro DF daquela fonte ser textual.
- **Cinema** — `cinema_grade.json` é a grade de **um cinema em um dia**:
  `[].movies[].rooms[].sessions[]`. O id do filme é estável e vira PK; o da
  sessão não é, e é por isso que `tratado.sessoes` é snapshot.
- **Instagram** — `instagram_post.json` é o payload cheio do Monid (347 chaves;
  a legenda mora em `caption.text`) e `instagram_extracao.json` é o que a visão
  devolveu **daquele mesmo post**: uma lista de eventos com `confianca`, que é
  a guarda por item. Ler os dois lado a lado é a forma mais rápida de entender
  o passo. O `story` fica de fora de propósito — mesma forma do post, e
  duplicaria dado de terceiro num repo público.
- **TMDB** — `tmdb_busca.json` guarda `candidatos` **e** `escolhido` para
  auditoria. `escolhido: null` é resposta legítima: o matching é título
  normalizado exato e, na dúvida, o filme fica sem nota.
- **Campos ricos que a derivação hoje ignora** — cavucar é exatamente para
  isso. Campo novo do bruto vira uma função em `src/tratamento/<fonte>.py` mais
  um `--so-derivar`, **sem re-raspar**.

## O que NÃO está aqui

A **listagem V2 do Ticket and Go**. Ela nunca chega ao `cru`: o payload
guardado sob a origem `catalogo` já é o detalhe da rota antiga (o `ERAS` de
`src/coleta/gravar.py` registra isso). Como a pasta é gerada a partir do `cru`,
o que a coleta descarta não tem exemplar — e é melhor a ausência do que um
arquivo que ninguém sabe se ainda corresponde ao que a fonte manda.
