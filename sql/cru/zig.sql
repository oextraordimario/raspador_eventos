-- CAMADA CRU (bronze) — ZIG (SuperTicket). Mesmo esqueleto e mesma politica do
-- cru/sympla.sql — o cabecalho la explica cada coluna.
--
-- A API do Zig NAO tem filtro server-side de estado: a coleta pagina o catalogo
-- nacional e filtra event_location.state == "DF" do lado de ca. O recorte roda
-- na COLETA, por decisao consciente (spec §6.7) — o que chega aqui ja e DF.

CREATE TABLE IF NOT EXISTS cru.zig (
    id_nativo  TEXT NOT NULL,   -- id na fonte, SEM o prefixo "zig:"
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
ALTER TABLE cru.zig ADD COLUMN IF NOT EXISTS visto_em TEXT;
UPDATE cru.zig SET visto_em = raspado_em WHERE visto_em IS NULL;
