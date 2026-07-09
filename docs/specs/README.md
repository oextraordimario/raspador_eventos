# Specs técnicas

Esta pasta guarda as **specs técnicas de implementação** — o "como" de cada peça do
MVP, um documento por spec (ex.: raspagem de cinema, enriquecimento por LLM via
subagente, migração para Postgres, instrumentação de uso).

Diferença dos outros docs:

- `docs/PRD_MVP.md` diz **o quê** e **por quê** (visão, escopo, roadmap) — a fonte da verdade.
- `docs/PROXIMOS_PASSOS.md` é o **backlog** priorizado.
- **`docs/specs/`** (aqui) detalha o **como** de um item antes de implementá-lo:
  contratos de dados, endpoints, decisões de design, casos de borda, plano de teste.

Convenção: uma pasta por spec, nomeada `AAAAMMDD_nome-em-kebab-case/`, com o
documento principal em `spec.md` (ex.: `20260709_mvp-fase-0/spec.md`). A pasta
pode guardar anexos da spec (diagramas, capturas de API, notas de calibração).
