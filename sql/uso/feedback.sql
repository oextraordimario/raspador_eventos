-- SCHEMA USO — **DADO DE PESSOA** (ver uso/usuarios.sql).
--
-- POLITICA DE RECUPERACAO: **NUNCA SE DROPA**; LGPD.
--
-- O que a pessoa escreveu no formulario de /feedback (NI-52, spec
-- 20260728_rework-site §7). Mora em `uso` e nao em `operacao` por causa de UM
-- campo: `contato`. Com ele a tabela passa a conter dado pessoal, e `uso` e o
-- schema que ja carrega essa politica.
--
-- E a PRIMEIRA escrita que o site publico faz na base. Nao ha upsert nem
-- dedupe: cada envio e uma linha, e o que protege a base do abuso e a rota
-- (honeypot, tetos de tamanho e teto por janela — servico/feedback.py).
--
-- O que NAO entra, de proposito: **IP e user-agent**. Seriam uteis para
-- reproduzir bug e para limitar abuso por origem, mas sao dado pessoal a mais
-- numa tabela que ja tem contato — e o teto por janela resolve o abuso sem
-- eles. Guardar IP "so para rate limit" e o tipo de decisao que se justifica
-- sozinha e nunca mais se reve.
--
-- ATENCAO na migracao: `id` e GENERATED ALWAYS AS IDENTITY — ver a nota em
-- operacao/execucoes.sql (OVERRIDING SYSTEM VALUE + setval).

CREATE TABLE IF NOT EXISTS uso.feedback (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    em        TEXT NOT NULL,              -- ISO UTC "+00:00"
    tipo      TEXT NOT NULL,              -- bug | sugestao | casa | outro
    mensagem  TEXT NOT NULL,
    contato   TEXT,                       -- OPCIONAL: e-mail ou @ (dado pessoal)
    pagina    TEXT,                       -- de onde a pessoa clicou
    lido      INTEGER NOT NULL DEFAULT 0  -- a CLI ferramentas/feedback.py marca
);

-- o teto por janela conta os envios dos ultimos 60s a cada POST, e o relatorio
-- da rodada conta os nao lidos: os dois passam por aqui
CREATE INDEX IF NOT EXISTS idx_feedback_em ON uso.feedback(em);
