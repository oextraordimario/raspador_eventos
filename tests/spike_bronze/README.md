# Spike NI-14 — camada Bronze (raspar payload na íntegra)

Spike do item `NI-14` do backlog (`docs/backlogs/nao-iniciado.yaml`): medir custo e
ganho de guardar o payload bruto de cada fonte (camada Bronze) e derivar o schema
unificado dele, em vez de normalizar direto no scraper.

**É um spike, não produção.** Nada aqui toca `src/` nem escreve em
`data/eventos.db` (a base é lida apenas para comparação). A captura intercepta o
`_normalizar` de cada scraper via monkeypatch durante uma raspagem normal.

## Perguntas que o spike responde (do NI-14)

- **(a) Custo** — quanto pesa guardar o bruto (bytes por evento, projeção da base)?
- **(b) Ganho** — quais campos existem no payload e são descartados hoje pelo
  `_normalizar`? O `--so-enriquecer`/UPSERT incremental (NI-15) não recuperam
  campo descartado — só o Bronze permite re-derivar sem re-raspar.
- **(c) Formato** — coluna `raw` em `eventos` vs. tabela `eventos_raw`
  (atenção: Sympla tem 2 payloads por evento — catálogo + BFF da página).

## Passos (rodar da raiz do repo)

```bash
# Passo 1 — captura os payloads brutos (rede; Shotgun usa Playwright, é o lento)
python -X utf8 tests/spike_bronze/capturar.py
python -X utf8 tests/spike_bronze/capturar.py --sem-shotgun

# Passos 2 e 3 — custo (tamanhos) + desperdício (campos não mapeados), offline
python -X utf8 tests/spike_bronze/analisar.py

# Passo 4 — re-derivação a seco: extrai um campo hoje descartado (ex.: preço)
# só do JSONL, sem nenhuma requisição nova, e compara com a base (dry-run)
python -X utf8 tests/spike_bronze/rederivar.py
```

O passo 5 (decisão) é humano: consolidar os números em `RESULTADO.md` e decidir
se o NI-14 vira spec própria ou vai para `docs/backlogs/rejeitado.yaml`.

Detalhes de captura:
- No Sympla, a produção pede à API só os campos que usa (parâmetro `only`); a
  captura **remove o `only`** para ver o payload completo — assim o diff separa
  "campo descartado pelo `_normalizar`" de "campo nem solicitado".
- Payload de detalhe (BFF do Sympla / `GET /events/{slug}` do Ingresse) é
  capturado por amostra (30 eventos por fonte). O JSON-LD do Shotgun já é o
  payload de detalhe.

## Assets gerados nesta pasta (gitignoráveis, regeráveis)

| arquivo | conteúdo |
|---|---|
| `sympla_catalogo.jsonl` | payload completo (sem `only`) por evento do catálogo |
| `sympla_evento.jsonl` | payload do BFF da página do evento (amostra) |
| `ingresse_catalogo.jsonl` | payload do `/events/search` por evento |
| `ingresse_evento.jsonl` | payload do `GET /events/{slug}` (amostra) |
| `shotgun_jsonld.jsonl` | JSON-LD (MusicEvent) por evento |
| `captura_meta.json` | contagens e timestamp da captura |
| `analise.json` | saída estruturada dos passos 2 e 3 |
| `RESULTADO.md` | números consolidados + decisão (passo 5) |

## Critérios de decisão (combinados antes de rodar)

- **Aprova** (vira spec) se: ≥ 2 campos úteis descartados hoje, re-derivação a
  seco funciona, e o bruto custa < ~5× o tamanho atual da base.
- **Rejeita** se: o descartado for majoritariamente lixo (ids internos, flags de
  UI) — aí NI-12/NI-13 se resolvem pontualmente, sem camada nova.
