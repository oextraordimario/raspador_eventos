# Spike: o Sympla inteiro, escrito dagster-first

Experimento de **desenho**, não candidato a produção. Rodado em 18/08/2026
contra `eventos_teste`.

O grafo de verdade (`src/pipeline/definitions.py`) é uma casca fina: cada asset
chama um passo de `pipeline/passos.py`, e o dado anda pelo Neon, de tabela em
tabela. Aqui é o oposto declarado — **a lógica mora no próprio arquivo do
Dagster e o dado passa de asset para asset** —, para dar de ver como fica um
desenho em que cada etapa é um nó com entrada e saída explícitas.

```bash
python src/ferramentas/dagster_dev.py --spike     # sobe junto do grafo real
```

Os dois grafos ficam lado a lado na mesma UI, em code locations chamadas
`raspador` (21 assets) e `spike_sympla` (7). É assim que a comparação se faz:
olhando, não lendo diff.

## A cadeia

```
sympla/catalogo  ── list[payload] ──┐
                                    ├─→ sympla/eventos ─ list[linha] ─┐
sympla/detalhes  ── {id: payload} ──┘                                 ├─→ spike/prata → spike/conferencia
sympla/tickets   ── {id: payload} ─── sympla/lotes ─ {id: [lote]} ────┘
```

Escreve em `spike.eventos` e `spike.lotes`, com as **mesmas 25 colunas** de
`tratado.eventos` — a estrutura que o site consome hoje. Não toca `cru`,
`tratado`, `curado` nem `operacao`.

A lógica do Sympla está escrita no arquivo: os três endpoints, a leitura de
cada payload, as colunas, os lotes. Não importa `coleta/sympla.py` nem
`tratamento/sympla.py`. Continuam vindo de fora apenas infra transversal
(`conexao`, `tempo`, `texto`) e o dicionário de bairros do DF — reimplementá-los
não testaria desenho nenhum e criaria uma segunda regra de negócio para
divergir da primeira.

## O run completo, ~1 minuto

| etapa | resultado |
|---|---|
| `sympla/catalogo` | 223 eventos futuros, 3 páginas, 98,7% do total do site (226) |
| `sympla/detalhes` | 40 buscados (teto da config), 0 reprovados na guarda, 5 sem id na URL |
| `sympla/tickets` | 29 payloads, 11 eventos fora da janela de 30 dias |
| `sympla/eventos` | 223 linhas, 0 rejeitadas, 223 com coordenada |
| `sympla/lotes` | 65 lotes em 27 eventos |
| `spike/prata` | 223 eventos + 65 lotes em `eventos_teste` |

## O que a conferência achou — o melhor do experimento

O asset `spike/conferencia` compara o resultado com o que o pipeline real
produziu em `tratado.eventos` para o Sympla. Resultado: 209 eventos em comum,
7 colunas divergindo **por construção** (o spike tem teto de detalhes e coleta
agora, então `descricao`, `categoria`, `cancelado`, `raspado_em` e as três de
preço divergem de propósito) e 7 divergências inesperadas.

**Uma era defeito do spike.** `bairro` nulo em **85 eventos**: a reescrita
embutida perdeu a canonização de bairro, que é uma etapa própria — a fonte
manda "Núcleo Bandeirante" e as grafias de "Asa Norte" em variações, e sem o
dicionário do DF a coluna fica vazia. Nenhum teste pegaria isso; foi a
comparação com a prata real que acusou.

**As outras seis não eram bug — era a fonte tendo mudado** desde a rodada de
14/08:

| coluna | linhas | o que aconteceu |
|---|---|---|
| `popularidade` | 12 | o score de trending do Sympla oscila |
| `imagem` | 5 | o produtor trocou a capa |
| `nome` | 2 | evento renomeado ("O Funk é Nosso!" → "CONVIDA: MC VINE7") |
| `url` | 2 | o slug acompanhou o renome |
| `start_date` / `end_date` | 1 | evento remarcado de 17 para 27/08 |

Se fosse parser errado, divergiria nas 209 linhas, não em duas. É a
demonstração mais direta de por que o `cru` é append-only, e de por que a
guarda de nome do NI-17 **só vale fresca**: o nome do catálogo se move sozinho,
e comparar um nome de hoje com um payload de quatro dias atrás reprovaria dado
bom.

## O que este desenho compra

Corrigir o `bairro` e reconferir custou re-materializar só as três etapas a
seco — `sympla/eventos`, `spike/prata`, `spike/conferencia` — em **1,4 segundo,
com zero requisição ao Sympla**. Os payloads vieram do IO manager.

Ou seja: é o `--so-derivar` acontecendo por **seleção de nó**, sem flag, sem
passo de CLI, sem ler o banco. E a fronteira "isto é rede, isto é a seco" deixa
de ser convenção escrita no CLAUDE.md e vira topologia do grafo — dá para
apontar na tela.

## O que ele perde

1. **Não há bronze.** O payload vive entre os assets e some quando o run é
   descartado. Sem `cru`: nada de reconstruir uma rodada passada a seco, nada
   de histórico de preço, e nada de `visto_em` — então `raspado_em` aqui é a
   hora da coleta, e não "a última vez que o evento apareceu no catálogo", que
   é o que a coluna significa na prata. Sem esse timestamp, a coluna `sumido`
   não teria como existir.
2. **Nada é incremental.** O `descrever` real pergunta ao cru quem ainda não
   tem payload de detalhe. Aqui a única fila possível é "todo mundo do
   catálogo", porque não há onde consultar o que já foi buscado — daí o teto de
   `limite_detalhes` na config, sem o qual o spike bate na fonte uma vez por
   evento a cada iteração de desenho.
3. **O dado trafega**, o que o grafo real proíbe por decisão (D8, §4.4).
   Funciona aqui porque é um processo só, numa máquina só. No servidor, o IO
   manager default grava em disco local e um run distribuído não acharia o
   arquivo — foi por isso que a decisão original foi essa.

Resumindo: **o spike compra clareza de grafo pagando com a camada medalhão.**
A pergunta que ele existe para responder não é "qual dos dois é melhor", e sim
*quanto dessa clareza dá para levar para o grafo real sem pagar esse preço* —
por exemplo, separar em nós distintos etapas que hoje moram dentro de um mesmo
compute, mantendo o dado no banco e a passagem de bastão em contagens.

## Duas armadilhas do caminho

- **`-f` repetido nomeia a code location pelo nome do arquivo.** Os dois
  grafos apareceriam como "dagster_dev.py" e "definitions.py" — sendo que o
  `definitions.py` é o spike, e o do pipeline real é o outro. O rótulo mentiria
  justamente na tela feita para comparar os dois. Por isso o `--spike` gera um
  `workspace.yaml` com `location_name` explícito.
- **`relative_path` no workspace resolve contra a pasta do YAML**, não contra
  o diretório de trabalho. Como o YAML é gerado em `.dagster/`, caminho
  relativo faz as duas locations falharem procurando `.dagster/src/...`. Vão
  caminho absoluto e `working_directory` explícito.
