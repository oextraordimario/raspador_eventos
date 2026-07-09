# Backlogs

Backlog do projeto em **dois YAMLs filtráveis** (formato herdado do projeto Karaoke,
enxugado em 2026-07-09: sem arquivos separados por estágio — o estágio virou o campo
`status`).

| Arquivo | O que vive aqui |
|---|---|
| [`nao-iniciado.yaml`](nao-iniciado.yaml) | **Todos os itens abertos**, com `status`: `pendente` (defeito/limitação conhecido com correção já desenhada — o TODO real) ou `nao-iniciado` (ideia exploratória ou de fase futura, sem compromisso). Semi-estruturado: código/prioridade/esforço/eixo/fase filtráveis + prosa no `detalhe` |
| [`rejeitado.yaml`](rejeitado.yaml) | Abordagem **testada e descartada** em favor de outra — mesmo schema, sem campos de priorização; registro pra não re-tentar sem motivo novo |

Ciclo de vida de um item:

- nasce em `nao-iniciado.yaml` (com `status` conforme o caso);
- quando ganha correção desenhada, muda o `status` para `pendente` (mesmo arquivo);
- **implementado de verdade → SAI do arquivo** (o git preserva; o registro do que
  entrou no fluxo é o commit e/ou a spec em [`docs/specs/`](../specs/));
- testado e descartado → move pra `rejeitado.yaml`, mantendo o código.

Convenções:

- **`NI-##`** é etiqueta estável (não é posição): item novo = próximo número livre; ao
  mover/remover, não renumerar. Rejeições que nasceram rejeitadas usam `RJ-##`.
- O roadmap por fases continua no **`docs/PRD_MVP.md`** (fonte da verdade do *quando*);
  aqui é o estoque de itens com o *o quê/como*.
- Este backlog **substitui o antigo `docs/PROXIMOS_PASSOS.md`** (2026-07-09; hoje um
  ponteiro).
