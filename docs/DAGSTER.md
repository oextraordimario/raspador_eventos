# Dagster — acesso à API

Instância de Dagster rodando no homelab do autor, exposta na tailnet via
Tailscale (`tailscale serve`, **não** Funnel). Ainda **não integrada ao
pipeline** — este documento registra o acesso verificado, para o dia em que a
orquestração migrar para lá.

## Endpoint

A URL **não é versionada**: o repositório é público e o host revela o nome da
máquina e o da tailnet. Ela mora no `.env` da raiz (gitignorado), como
`DAGSTER_URL`, e o formato é `https://<host>.<tailnet>.ts.net:8443/graphql`.

```bash
# como carregar em qualquer shell da raiz do repo
export DAGSTER_URL=$(grep -oP '(?<=^DAGSTER_URL=).*' .env)
```

Isso é **precaução, não a proteção**: o que impede acesso de fora é o `serve`
(veja abaixo), não o segredo do nome.

- **Transporte:** HTTPS com certificado do Tailscale (valida sozinho, sem `-k`).
- **Método:** só **POST**. `GET /graphql` responde **400** — isso é o normal do
  endpoint, não é o servidor fora do ar.
- **Autenticação:** **nenhuma**. Quem alcança a tailnet consulta e também
  **dispara e mata execuções** (`launchPipelineExecution`, `terminatePipelineExecution`).
  Se a tailnet passar a ser compartilhada com terceiros, restringir por ACL do
  Tailscale antes de qualquer outra coisa.
- **Alcance:** só de dentro da tailnet, porque está em `tailscale serve`. Runner
  do GitHub Actions **não** enxerga — qualquer coisa que dependa disto é rodada
  local (mesma classe da `--rodada-local`).
- **A porta 8443 é uma das três do Funnel** (443, 8443, 10000). Se algum dia isto
  virar `tailscale funnel`, o endpoint sem autenticação passa a estar exposto à
  internet inteira, e de fora responde igualzinho ao `serve` — nenhum teste feito
  de dentro da tailnet distingue os dois. Quem responde é `tailscale serve status`
  / `tailscale funnel status` na máquina. Conferido em 14/08/2026: **serve**.

## Estado verificado em 14/08/2026

| | |
|---|---|
| Versão do Dagster | **1.13.17** |
| Code location | `definitions.py` |
| Repositório | `__repository__` |
| Jobs | `__ASSET_JOB` (o job implícito de assets) |
| Assets | `hello_homelab` (grupo `default`) |

Ou seja: instância recém-subida, ainda com o asset de exemplo. Nada do raspador
está lá.

## Como testar / consultar

```bash
# versão (o "ping" mais barato)
curl -s -X POST "$DAGSTER_URL" \
  -H "Content-Type: application/json" -d '{"query":"{ version }"}'

# code locations, repositórios e jobs
curl -s -X POST "$DAGSTER_URL" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ repositoriesOrError { ... on RepositoryConnection { nodes { name location { name } pipelines { name } } } ... on PythonError { message } } }"}'

# assets
curl -s -X POST "$DAGSTER_URL" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ assetsOrError { ... on AssetConnection { nodes { key { path } definition { groupName computeKind } } } ... on PythonError { message } } }"}'
```

## Armadilhas

- **O schema é o do Dagster 1.13** — o campo para listar assets é
  `assetsOrError`; `assetNodesOrError` (que aparece em muito exemplo e na
  memória dos LLMs) **não existe aqui** e devolve erro de campo desconhecido.
  Os vizinhos válidos: `assetOrError`, `assetNodeOrError`, `assetRecordsOrError`.
- **Toda query de `*OrError` é união** com `PythonError` — sempre abrir os dois
  ramos com `... on`, senão um erro do lado do Dagster volta como resposta vazia
  sem explicação.
- **400 em GET não é falha de acesso.** Para saber se o servidor está de pé, o
  teste é o POST de `{ version }`, não um `curl` na URL.
- **Não colar a URL em doc, spec, teste ou mensagem de commit.** Ela saiu do
  histórico uma vez (reescrita de 14/08/2026) justamente por isso; sempre por
  `$DAGSTER_URL`.
