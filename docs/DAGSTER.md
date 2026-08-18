# Dagster — a instância do homelab

Instância de Dagster rodando no homelab do autor, exposta na tailnet via
Tailscale (`tailscale serve`, **não** Funnel). A migração da orquestração para
lá está em curso — spec `20260814_orquestracao-dagster`, fatia a fatia; este
documento registra o acesso à API e como rodar o mesmo grafo no laptop.

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

## Dagster no laptop

O grafo de `src/pipeline/definitions.py` roda aqui também, com UI, contra a
base de **teste**:

```bash
# 1ª vez: o venv dedicado (3.12, a mesma minor da imagem do servidor)
py -3.12 -m venv .venv-dagster
.venv-dagster/Scripts/python.exe -m pip install -r requirements-dagster.txt

# sempre: da raiz do repo, com o python que estiver à mão
python src/ferramentas/dagster_dev.py        # UI em http://127.0.0.1:3070
```

Serve para encurtar o laço de quem mexe no grafo: ver o efeito de uma mudança
no servidor custa commit → push → `git pull` → `docker compose restart
raspador_code`; aqui custa um F5. O que mais se ganha é o que só se vê
olhando — agrupamento, nome de chave, o que o desenho explica.

**Por que um script, e não `dagster dev` na mão.** O `.env` da raiz tem
`EVENTOS_DB_URL` de **produção**, e um grafo apontado para lá materializa de
verdade: um clique em `tratamento` reconstrói a prata de produção. O script
redireciona a conexão para a base de teste — e faz isso por
`conexao.DB_URL`, o mesmo caminho de `tests/base_teste.py`, com guarda de nome
(URL sem "teste" não sobe). A conferência em run é a de sempre:
`operacao/schema` publica `base=` na metadata; se não disser `eventos_teste`,
pare.

> ⚠️ **Variável de ambiente não segura isto** — medido em 18/08/2026. O CLI do
> Dagster lê o `.env` do diretório de trabalho e o injeta com
> `os.environ[chave] = valor`, ou seja **sobrescrevendo** o que o processo já
> tinha. Passar `EVENTOS_DB_URL=<teste>` ao subprocesso parece bastar e não
> basta: numa sonda que só imprimia o nome do banco visto pelo step, a URL
> passada era `.../BANCO_DE_TESTE_FALSO` e o step leu `eventos`. Por isso o
> redirecionamento é em Python, não no ambiente.
>
> Corolário para o servidor: se um dia aparecer um `.env` dentro de
> `/srv/raspador_eventos`, ele passa a **vencer** o `env_file` do compose. Hoje
> não existe — o clone é limpo e o `.env` é gitignorado.

Antes de commitar mudança de grafo, a checagem barata (não sobe UI, só carrega
o arquivo e reclama):

```bash
.venv-dagster/Scripts/python.exe -m dagster definitions validate -f src/pipeline/definitions.py
```

**Diferenças assumidas em relação ao servidor:** storage local é SQLite em
`.dagster/` (gitignorado, descartável — o histórico que vale é o do Postgres da
instância); não há `dagster.yaml`, então valem os defaults, e config de
instância (pools, concorrência, retenção) só existe lá; a porta é 3070 porque a
3000 é onde o `next dev` cai.

**A versão é pinada em três lugares** — `homelab/dagster/Dockerfile`,
`docker/raspador_code.Dockerfile` e `requirements-dagster.txt` — e sobe nos
três no mesmo commit. Divergir entre daemon e code location dá "location failed
to load"; divergir com o laptop é pior, porque o grafo abre aqui e quebra só lá.

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
