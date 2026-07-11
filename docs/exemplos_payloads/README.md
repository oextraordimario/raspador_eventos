# Exemplos de payload bruto (camada Bronze)

Um evento real de cada fonte, com **todos os payloads** que a Bronze
(`eventos_raw`) guarda dele, pretty-printed para cavucar. Snapshot de
**2026-07-10** — os arquivos são cópia congelada para referência/estudo; a
fonte da verdade viva é a tabela `eventos_raw` em `data/eventos.db`
(explorável em `tests/manuais/explorar_dados.ipynb`, seção "Camada Bronze").

> **Dados mascarados:** e-mail/telefone de organizador e tokens
> (`invitationToken`, `authToken`) foram substituídos por valores fictícios
> antes de publicar o repo — a estrutura é fiel, esses valores não.

| arquivo | evento | endpoint de origem |
|---|---|---|
| `sympla_catalogo.json` | HOUSE CLUB 13 ANOS | `discovery-bff/search` (listagem, sem `only` — payload cheio) |
| `sympla_detalhe.json` | idem | `event-page.svc.sympla.com.br/api/event-bff/purchase/event/{id}` (passo "descrever") |
| `sympla_tickets.json` | idem | `.../event/{id}/tickets` (passo "precificar") |
| `ingresse_catalogo.json` | Passaporte 3 DIAS - Festa da Lili 21 anos | `api-site.ingresse.com/events/search` |
| `ingresse_detalhe.json` | idem | `api-site.ingresse.com/events/{slug}` (passo "descrever") |
| `ingresse_tickets.json` | idem | `api-embedstore.ingresse.com/.../session/.../tickets` (passo "precificar"; este é um evento-passaporte, veio do fallback `passports`) |
| `shotgun_catalogo.json` | Infinu Recebe Leoa Em Brasília | JSON-LD `MusicEvent` da página do evento (Playwright); não há `detalhe`/`tickets` — descrição e `offers[]` já vêm aqui |

## Onde olhar primeiro

- **Lotes/preços (caso NI-18):** `sympla_tickets.json` → array `tickets[]`
  (`name`, `isFree`, `salePriceWithDiscountMonetary.decimal` — R$ **já com
  taxa**: 49,50 = 45 + 4,50 —, `feeMonetary`, `currentAvailableQty`; repare na
  CORTESIA FEMININA que colapsa o `preco_min` para 0).
  `ingresse_tickets.json` → `detail.responseData[].type[]` (`price` **sem**
  taxa, `tax` separada, `status`, `hidden`). `shotgun_catalogo.json` →
  `offers[]` (`name`, `price` total, `availability`).
- **Derivações da Prata:** `sympla_catalogo.json` → `location.neighborhood`
  (bairro) e `global_score` (popularidade); `sympla_detalhe.json` →
  `cancelled`; `shotgun_catalogo.json` → `eventStatus`.
- **Campos ricos descartados hoje** (candidatos a derivação futura): cavucar é
  exatamente para isso.

## Regenerar / trocar o evento exemplo

Os arquivos saíram da Bronze com:

```python
json.dumps(json.loads(payload), indent=2, ensure_ascii=False)
```

para os eventos `sympla:3459772`, `ingresse:89750` e `shotgun:leoaembsb`.
Para trocar o exemplar, use `raw_de("<nome>")` no notebook e salve o que
interessar — ou peça ao agente.
