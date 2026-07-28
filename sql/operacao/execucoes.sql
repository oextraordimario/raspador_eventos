-- SCHEMA OPERACAO — telemetria do pipeline e artefatos nossos. Nao e dado de
-- fonte (por isso nao e cru) nem se reconstroi de nada (por isso nao e tratado).
--
-- POLITICA DE RECUPERACAO: **NUNCA SE DROPA**. Registra o que aconteceu uma vez;
-- nao ha como refazer.
--
-- Observabilidade da rodada: uma linha por execucao do atualizar.py, para o
-- relatorio comparar com a rodada anterior e alertar queda de coleta (scraper
-- quebrado em silencio — a hipotese de risco nº 1 do produto). Campos compostos
-- ficam como JSON em TEXT de proposito: tabelas relacionais seriam custo de
-- schema sem consulta que o justifique (quem le e gente depurando + o proprio
-- relatorio). Spec: docs/specs/20260710_alinhamento-constituicao/spec.md.
--
-- ATENCAO na migracao: `id` e GENERATED ALWAYS AS IDENTITY. Copiar esta tabela
-- com INSERT ... SELECT * FALHA sem OVERRIDING SYSTEM VALUE, e a sequence da
-- copia nasce em 1 — precisa de setval, ou o primeiro registrar_execucao()
-- depois colide na PK.

CREATE TABLE IF NOT EXISTS operacao.execucoes (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    iniciada_em TEXT NOT NULL,    -- ISO 8601 UTC do inicio da rodada
    duracao_s   DOUBLE PRECISION, -- duracao total em segundos
    modo        TEXT NOT NULL,    -- completo | sem-shotgun | cron | rodada-local | so-derivar | so-enriquecer
    fontes      TEXT,             -- JSON {fonte: {coletados, total_site} | {erro}}
    passos      TEXT,             -- JSON {descrever, precificar, derivado, ruido, dedupe_grupos, sumidos}
    erros       TEXT              -- JSON [{passo, evento_id, erro}] — falha POR EVENTO
);
