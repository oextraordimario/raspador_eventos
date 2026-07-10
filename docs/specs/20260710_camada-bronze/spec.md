# Spec — Camada Bronze: payload bruto por evento

> **Status:** **implementada** em 2026-07-10 (mesmo dia da spec): `eventos_raw`
> no schema, `_raw` nos 3 scrapers, `src/derivar.py` + `--so-derivar` no
> pipeline; teste de fumaça em `tests/test_bronze.py`. O bug do Bileto (NI-17)
> foi corrigido antes, como pré-requisito (§2). Spike de origem (NI-14,
> **aprovado**): medições e veredito em
> [`tests/spike_bronze/RESULTADO.md`](../../../tests/spike_bronze/RESULTADO.md).
> **O quê/por quê:** guardar o JSON/JSON-LD bruto que cada fonte devolve, por
> evento, para (1) re-derivar campos novos **sem re-raspar** e (2) auditar a
> corretude da base contra a origem. Esta spec é o **como**.

---

## 1. Objetivo

Hoje cada scraper normaliza direto (payload → dict do schema) e tudo que o
`_normalizar` não mapeia é descartado na origem. A Bronze inverte isso: o bruto
é **guardado junto** do normalizado, e campo novo vira função de derivação que
roda a seco sobre a base.

Duas entregas:

1. **Guardar o bruto** das 3 fontes numa tabela própria (`eventos_raw`),
   preenchida no mesmo fluxo de raspagem de hoje.
2. **Derivação a seco**: um passo `derivar` no pipeline que (re)calcula colunas
   do schema a partir de `eventos_raw`, sem rede — no espírito do
   `--so-enriquecer`.

## 2. Decisões já tomadas (do spike, não rediscutir)

- **Tabela própria, não coluna `raw` em `eventos`:** o Sympla tem **2 payloads
  por evento** (catálogo + BFF da página); coluna única não comporta.
- **Sympla passa a raspar o catálogo sem `only`:** o payload completo custa
  ~1,2 KB/evento (21× o reduzido, ainda KB) e é onde moram `neighborhood` e
  `global_score`. Sem isso a Bronze do Sympla nasceria capada.
- **Custo aceito:** bruto completo projetado em ~4,6 MB para Brasília
  (~5,7× a base atual de ~1 MB) — trivial em absoluto. **Sem poda nem
  compressão na 1ª entrega**; se pesar, podar as chaves-lixo conhecidas do BFF
  do Sympla (`eventPaymentOptions`, `integrations.*`) antes de comprimir.
- **Preço de Sympla/Ingresse fica fora:** o spike provou que ele **não está**
  nos payloads atuais (NI-12 exige endpoint de tickets; segue item próprio).
- **Bug do Bileto (NI-17) é pré-requisito lógico:** o passo "descrever" grava
  detalhe de evento ERRADO para URLs `bileto.sympla.com.br` — corrigir antes ou
  junto, senão a Bronze eterniza payload alheio.

## 3. Fora de escopo

Campos de produto derivados (ranking por popularidade, filtro "esgotado" na
consulta, bairro na busca) — cada um vira item/spec próprio depois que a Bronze
existir; aqui só se prova a mecânica com 1 campo. Histórico/versionamento de
payload (guardamos só o último). Poda/compressão. Outras cidades.

## 4. Design

### 4.1 Schema (`sql/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS eventos_raw (
    evento_id  TEXT NOT NULL,  -- eventos.id ("<fonte>:<id_nativo>")
    origem     TEXT NOT NULL,  -- qual payload: 'catalogo' | 'detalhe'
    payload    TEXT NOT NULL,  -- JSON bruto, como veio da fonte (json.dumps ensure_ascii=False)
    raspado_em TEXT NOT NULL,  -- ISO 8601 UTC
    PRIMARY KEY (evento_id, origem)
);
```

Último payload vence (UPSERT na PK). **Base é descartável** (CLAUDE.md): mudar
o schema = apagar `data/eventos.db` e re-raspar; `atualizar.py` já instrui.

### 4.2 Scrapers — chave reservada `_raw`

Contrato mínimo, sem mudar assinatura de `raspar()`: o dict normalizado ganha a
chave reservada **`_raw`** (o payload de origem), que `store.upsert_eventos`
**remove** do dict e grava em `eventos_raw` com `origem='catalogo'`
(Shotgun: o JSON-LD já é o detalhe, mas entra como `catalogo` por ser o payload
do fluxo principal — a distinção que importa é "payload extra do descrever").

- `sympla.py`: remover `only` da chamada (manter `CAMPOS` documentado como
  registro do que o `_normalizar` usa); `_normalizar` devolve `_raw=ev`.
- `ingresse.py`: `_normalizar` devolve `_raw=ev`.
- `shotgun.py`: `_normalizar` devolve `_raw=ld`.
- `raspar_descricao` (Sympla/Ingresse) passa a devolver também o payload
  inteiro; `atualizar._descrever` grava `origem='detalhe'`.

### 4.3 Derivação a seco (`src/derivar.py` + passo no `atualizar.py`)

Funções puras `payload -> {coluna: valor}` por (fonte, origem), aplicadas em
lote lendo `eventos_raw` e escrevendo em `eventos` (mesmo espírito do
`enriquecer.aplicar`: idempotente, recalcula tudo). Entra no pipeline após o
"descrever" e ganha flag `--so-derivar` (sem rede, como `--so-enriquecer`).

**Campo-prova da 1ª entrega:** `bairro` (Sympla `location.neighborhood`;
Shotgun já tem em `endereco`) — nova coluna em `eventos`, ainda **sem** uso na
consulta (produto decide depois). Validado no spike: 124/259 eventos Sympla.

### 4.4 Casos de borda

- **JSON com ` `/` `** (separadores Unicode em descrições): inofensivo
  como TEXT no SQLite, mas **nunca** reler dump com `splitlines()` — o spike
  tropeçou nisso (`tests/spike_bronze/analisar.py` documenta).
- **Evento que some do catálogo:** a linha em `eventos_raw` fica (órfã como o
  próprio evento em `eventos` — comportamento atual, nada muda).
- **Payload de detalhe errado (Bileto):** ver NI-17; com a validação de nome
  no `_descrever`, o payload suspeito **não** é gravado.

## 5. Plano de teste

Estender/juntar aos testes de fumaça (`tests/`, scripts executáveis, base
descartável em arquivo temporário):

1. `upsert_eventos` com `_raw` grava `eventos_raw` e **não** vaza `_raw` como
   coluna de `eventos`; upsert repetido não duplica (PK).
2. `derivar.aplicar` preenche `bairro` a partir do bruto e é idempotente.
3. Fluxo `--so-derivar` roda sem rede numa base já populada.
4. Relatório do `atualizar.py` ganha a linha "payloads brutos por origem"
   (cobertura da Bronze ao lado da cobertura de descrição).

## 6. Referências

- Spike (medições, scripts e assets): `tests/spike_bronze/`
- Item de origem: NI-14 (saiu de `docs/backlogs/nao-iniciado.yaml` com esta spec)
- Bug relacionado descoberto no spike: NI-17 (Bileto)
