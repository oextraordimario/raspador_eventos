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

-- Mudanca ADITIVA (fatia 7): `visto_em` = a ultima vez que ESTE payload foi
-- visto identico na fonte, e nao a vez em que ele MUDOU.
--
-- POR QUE ELA PRECISA EXISTIR. O append-only nao grava versao nova quando o
-- payload nao mudou — entao `raspado_em` e a data da ultima MUDANCA. Usa-lo
-- como ancora do `sumido` marcaria como "sumiu do catalogo" todo evento que
-- simplesmente nao mudou desde a rodada passada. `visto_em` avanca em toda
-- coleta, sem custar linha nova, e e ele que vira tratado.eventos.raspado_em.
--
-- O `CREATE TABLE IF NOT EXISTS` acima nao altera tabela que ja existe: por
-- isso o ALTER ao lado. O UPDATE e o backfill unico das linhas anteriores a
-- coluna (idempotente — depois da primeira vez nao casa nenhuma linha).
ALTER TABLE cru.ingresse ADD COLUMN IF NOT EXISTS visto_em TEXT;
UPDATE cru.ingresse SET visto_em = raspado_em WHERE visto_em IS NULL;
