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
