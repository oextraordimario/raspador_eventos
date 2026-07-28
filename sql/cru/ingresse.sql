-- CAMADA CRU (bronze) — INGRESSE. Mesmo esqueleto e mesma politica do
-- cru/sympla.sql (append-only, nunca se dropa, hash sha256 canonico, `api`
-- declarada pela coleta) — o cabecalho la explica cada coluna.

CREATE TABLE IF NOT EXISTS cru.ingresse (
    id_nativo  TEXT NOT NULL,   -- id na fonte, SEM o prefixo "ingresse:"
    origem     TEXT NOT NULL,   -- 'catalogo' | 'detalhe' | 'tickets'
    raspado_em TEXT NOT NULL,
    hash       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    api        TEXT,
    PRIMARY KEY (id_nativo, origem, raspado_em)
);
