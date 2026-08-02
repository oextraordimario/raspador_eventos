# Linhagem de dados: o que existe em open source e o que serve aqui

**Data:** 2026-08-02 · **Pergunta:** o projeto cresceu em número de tabelas e
etapas; existe ferramenta pronta, open source, que desenhe a trajetória do dado
— fonte original, como foi raspado, por quais scripts passou?

**Resposta curta:** existe ferramenta boa, e nenhuma se encaixa aqui sem virar
um elefante. O motivo não é tamanho: é que **a transformação deste projeto é
Python, não SQL**, e é de SQL que as ferramentas automáticas vivem.

---

## 1. O panorama

| Ferramenta | O que é | Peso operacional |
|---|---|---|
| **OpenLineage** + **Marquez** | OpenLineage é o *padrão* (spec de eventos de linhagem, JSON sobre HTTP/Kafka); Marquez é o backend + UI que recebe os eventos e desenha o grafo. É o único projeto do mercado que faz **só linhagem**, sem catálogo/governança em cima. LF AI & Data, graduado em set/2023, ativo (Astronomer é o maior contribuidor; desde a 0.54 o backend foi reescrito em Rust). Sem oferta gerenciada — ou se auto-hospeda, ou não se usa. | Docker: backend + Postgres próprio + UI React |
| **DataHub** | Catálogo completo com grafo de metadados, linhagem coluna-a-coluna, ownership, glossário | Alto |
| **OpenMetadata** | Mesma categoria do DataHub; linhagem tabela e coluna, explorador visual | Alto |
| **sqllineage** / **LineageX** / **Tokern** | Bibliotecas Python que **inferem linhagem lendo SQL**. LineageX tem foco em Postgres e gera grafo interativo; sqllineage é embutível em CI; Tokern lê histórico de queries | Baixo |
| **Hamilton** | Não é ferramenta de linhagem: é um jeito de *escrever* pipeline em Python onde cada transformação é uma função, e o grafo cai de graça (integra com OpenLineage) | Reescrever o pipeline |

## 2. Por que nada disso encaixa direto

**(a) O parser de SQL fica cego aqui.** Toda ferramenta automática deriva a
linhagem de um de dois lugares: parsing de SQL, ou hooks de orquestrador
(Airflow, dbt, Spark, Dagster). Este pipeline não tem nenhum dos dois. Um
`sqllineage`/`LineageX` olharia `tratamento/comum.py`, veria o `INSERT INTO
tratado.eventos (...)` e **não teria como saber que aquilo veio de `cru.sympla`
através de `tratamento/sympla.py`** — que é exatamente a pergunta a responder.
Ele desenharia um grafo mudo.

**(b) O Marquez também não descobre nada sozinho.** Sem Airflow/dbt, alguém tem
que emitir os eventos à mão pelo `openlineage-python`, declarando entrada, saída
e job em cada passo. Ou seja: **em qualquer cenário o grafo é escrito à mão** — a
única escolha real é *onde ele mora* (num serviço externo ou no próprio repo).

**(c) Proporção.** São 8 fontes e ~31 objetos entre tabelas e views. Marquez e
DataHub existem para centenas de assets que ninguém mais segura na cabeça.

**(d) Metade da linhagem de runtime já existe na base**, e não estava desenhada:
`operacao.coletas` (quem coletou, quando, quantos, se falhou), `operacao.execucoes`
(histórico de rodadas), `visto_em`/`raspado_em` no cru, `gravar.ERAS` (qual
endpoint produziu cada payload) e `operacao.slugs` (histórico de endereço). O que
faltava era uma **tela**, não instrumentação.

## 3. Decisão

**Nível 1 — feito (2026-08-02).** Gerador estático que lê o próprio código e
cospe um Mermaid versionado:

```
python src/ferramentas/linhagem.py     # regrava docs/linhagem/LINHAGEM.md
```

A vantagem que ferramenta nenhuma dá: **não pode ficar desatualizado**, porque a
fonte é o código, não um cadastro paralelo. Fonte nova aparece no diagrama
sozinha. Zero infra, zero container, zero custo recorrente. O que ele lê:

- `coleta/gravar.py` → `FONTES`, `ERAS` (endpoint por fonte×origem)
- `tratamento/comum.py` → `TRILHAS`; cada `tratamento/<fonte>.py` → `DERIVACOES`,
  `LOTES`, `CONFERIR`
- `tratamento/ciclo.py` → a ordem real dos passos a seco (por AST da `executar`)
- `sql/**/*.sql` → os objetos de cada camada, a política declarada no cabeçalho e
  as dependências das views de `public`
- os módulos `.py` → quem lê e quem escreve cada tabela qualificada
- quem importa `servico/consulta.py` → as portas de consumo

**Nível 2 — não feito, e só se a pergunta mudar.** No dia em que a pergunta virar
*"de onde veio ESTE evento, em qual rodada, com qual payload"* — linhagem de
instância com histórico, não de estrutura —, o caminho é `openlineage-python`
emitindo de `pipeline/atualizar.py` e `tratamento/ciclo.py`, com Marquez em Docker
local. Por ser padrão aberto, trocar o destino para DataHub depois é configuração.
Não fazer antes de ter a pergunta.

**Descartados:** DataHub e OpenMetadata (desproporcionais ao tamanho e ao time de
uma pessoa); sqllineage/LineageX/Tokern (cegos ao Python, que é onde a
transformação mora); Hamilton (exigiria reescrever o tratamento para ganhar um
grafo que o nível 1 dá de graça).

## 4. Fontes

- [Marquez — GitHub](https://github.com/MarquezProject/marquez) e [LF AI & Data](https://lfaidata.foundation/projects/marquez/)
- [OpenLineage — cliente Python](https://openlineage.io/docs/client/python/)
- [Open Source Data Lineage: Tools and Tradeoffs (DataHub)](https://datahub.com/blog/open-source-data-lineage/)
- [10 Best Open Source Data Lineage Tools 2026 (Data Stack Hub)](https://www.datastackhub.com/top-tools/open-source-data-lineage-tools/)
- [Best Open-Source Tools for Column-Level Lineage (Galaxy)](https://www.getgalaxy.io/learn/glossary/open-source-tools-that-offer-column-level-lineage)
- [LineageX: A Column Lineage Extraction System for SQL (arXiv)](https://arxiv.org/html/2505.23133v1)
- [openmetadata-sqllineage — GitHub](https://github.com/open-metadata/openmetadata-sqllineage)
- [Open Source Python Data Lineage with OpenLineage and Hamilton](https://medium.com/@stefan.krawczyk/open-source-python-data-lineage-with-openlineage-and-hamilton-fe599c0459d6)
