# Resultado do spike NI-14 — camada Bronze

Executado em 2026-07-10, captura real de Brasília (259 Sympla + 4 Ingresse +
75 Shotgun; detalhe por amostra de 30). Números completos em `analise.json`,
`rederivacao.json` e `captura_meta.json`.

## (a) Custo — pequeno em absoluto, mediano em proporção

| payload | eventos | tamanho | por evento |
|---|---:|---:|---:|
| Sympla catálogo (sem `only`) | 259 | 315 KB | ~1,2 KB |
| Sympla BFF da página (amostra) | 30 | 449 KB | ~15,3 KB |
| Ingresse catálogo | 4 | 4 KB | ~1,0 KB |
| Ingresse detalhe (amostra) | 4 | 57 KB | ~14,6 KB |
| Shotgun JSON-LD | 75 | 274 KB | ~3,7 KB |

- Snapshot capturado: **1,1 MB**. Extrapolando o detalhe do Sympla para o
  catálogo inteiro (259 × 15,3 KB ≈ 3,9 MB): bruto total **≈ 4,6 MB** →
  base ≈ 5,5 MB, **~5,7× a base atual (976 KB)**.
- Fica um pouco acima do limiar combinado (5×), mas em termos **absolutos é
  trivial** para uma cidade. E o BFF do Sympla (o vilão dos 15 KB) é ~90% lixo
  (opções de pagamento, pixels de Facebook): poda de chaves conhecidas ou
  compressão (zlib) derruba isso com folga.

## (b) Ganho — o desperdício é real e tem campo útil

Campos preenchidos hoje descartados pelo `_normalizar`:

- **Sympla**: `location.neighborhood` (bairro, 48%), `global_score`
  (popularidade/trending, 100% — daria ranking à consulta). Boa parte só
  aparece porque a captura removeu o `only` — em produção nem são solicitados.
- **Ingresse**: `session.status` (available), `place.externalId` (**id do
  Google Maps** — ouro para o dedupe cross-fonte de local), `sessions[]` no
  detalhe (evento multi-dia tem várias sessões; a base guarda 1 data).
- **Shotgun**: `doorTime` (hora de abertura), `eventStatus` (cancelamento),
  `offers[].availability` (**esgotado**), `offers[].name` (lote),
  `offers[].priceCurrency`.

Achado negativo honesto: **preço do Sympla e do Ingresse não está em nenhum
payload capturado** (no Sympla só `serviceFee`). O Bronze **não resolve o
NI-12 sozinho** nessas duas fontes — preço exige outro endpoint (tickets).

## Re-derivação a seco — funciona (a promessa do Bronze)

Só com os JSONL, zero requisições novas (`rederivar.py`): **338 eventos
ganhariam ≥ 1 campo novo** — popularidade (259), bairro (124), esgotado /
cancelado / abre_às (75), nº de sessões (4).

## Bônus — o Bronze pagou o spike: bug real encontrado por auditoria

Auditando payload vs. base: **5 eventos do Bileto** (`bileto.sympla.com.br`)
estão na base com **descrição e categoria de eventos alheios**. Causa: o
`_descrever` do `atualizar.py` extrai o id numérico do fim da URL, mas o id
do Bileto é de outro namespace — o BFF de página devolve *outro evento* (ex.:
"The Beatles Abbey Road" virou `curso-workshop` com descrição de menu de
polvo — e o FTS indexa essa descrição errada). **Fix sugerido (independente
do Bronze):** pular URLs `bileto.sympla.com.br` no `_descrever`, e/ou validar
o nome retornado contra o da base antes de gravar.

## (c) Formato — tabela própria, não coluna

Sympla tem **2 payloads por evento** (catálogo + BFF da página); coluna única
`raw` em `eventos` não comporta. Formato indicado:
`eventos_raw(evento_id, origem, payload TEXT, raspado_em, PRIMARY KEY (evento_id, origem))`.

## Recomendação

**Aprovar** o NI-14 e virar spec própria:

- ≥ 2 campos úteis descartados hoje ✔ (bairro, popularidade, esgotado,
  cancelado, externalId, sessões…)
- Re-derivação a seco funciona ✔ (338 eventos enriquecidos sem re-raspar)
- Custo: 5,7× em proporção, mas ~5,5 MB em absoluto — aceitável, e cai com
  poda/compressão do BFF do Sympla ✔ (com ressalva)
- Bônus comprovado: auditoria contra a origem achou bug real (Bileto) ✔

Ressalvas para a spec: (1) preço Sympla/Ingresse fica de fora (NI-12 precisa
de endpoint de tickets); (2) capturar o catálogo do Sympla **sem `only`**
passa a ser necessário (payload completo é 21× o peso do reduzido, mas ainda
KB); (3) tratar o bug do Bileto antes/junto.
