-- SCHEMA USO — **DADO DE PESSOA** (ver uso/usuarios.sql).
--
-- POLITICA DE RECUPERACAO: **NUNCA SE DROPA**; LGPD.
--
-- Uma linha por chamada de tool. Registra a INTENCAO (os argumentos, incl. o
-- texto buscado): e o insumo de produto da abertura ao publico, nao so contagem
-- de trafego. sub NULL = chamada local (stdio, sem auth).
--
-- ATENCAO na migracao: `id` e GENERATED ALWAYS AS IDENTITY — ver a nota em
-- operacao/execucoes.sql (OVERRIDING SYSTEM VALUE + setval).

CREATE TABLE IF NOT EXISTS uso.acessos (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sub        TEXT,
    em         TEXT NOT NULL,     -- ISO UTC "+00:00"
    tool       TEXT NOT NULL,
    args       TEXT,              -- JSON dos argumentos da chamada
    resultados INTEGER,           -- nº de itens devolvidos (quando devolve lista)
    ms         INTEGER,
    erro       TEXT
);
CREATE INDEX IF NOT EXISTS idx_acessos_sub_em ON uso.acessos(sub, em);
