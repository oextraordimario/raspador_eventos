-- CAMADA TRATADO (prata) do dominio CINEMA (NI-07): derivada 100% de
-- cinema_raw, a seco. O id do filme na Ingresso.com e estavel entre semanas (ao
-- contrario do sessionId), e por isso e a PK.
--
-- POLITICA DE RECUPERACAO: 100% descartavel — derivar.aplicar_cinema reconstroi
-- filmes e sessoes do zero a partir do cru a cada rodada (SNAPSHOT).
--
-- O dominio cinema NAO entra em eventos: sessao e volatil e sem id nativo
-- estavel entre semanas. Spec: docs/specs/20260711_raspagem-cinema/.

CREATE TABLE IF NOT EXISTS filmes (
    id            TEXT PRIMARY KEY,  -- id do filme na Ingresso.com
    titulo        TEXT NOT NULL,
    titulo_original TEXT,            -- originalTitle da fonte; chave do matching TMDB (NI-36)
    generos       TEXT,              -- "Animacao, Aventura" (mesmo estilo de eventos.categoria)
    duracao_min   INTEGER,
    classificacao TEXT,              -- classificacao indicativa, texto da fonte
    distribuidora TEXT,
    url           TEXT,              -- pagina do filme na Ingresso.com
    poster        TEXT,
    poster_proprio TEXT,             -- copia no storage proprio (NI-37); NULL = front usa poster
    trailer       TEXT,
    em_pre_venda  INTEGER NOT NULL DEFAULT 0,  -- 1 = so em pre-venda (inPreSale)
    -- enriquecimento externo (NI-36): derivado de cinema_extra_raw, nao da grade
    sinopse       TEXT,              -- pt-BR (TMDB)
    ano           INTEGER,           -- ano de lancamento
    nota          DOUBLE PRECISION,  -- 0-10 (TMDB vote_average; NULL = sem match ou sem votos)
    votos         INTEGER,
    tmdb_id       TEXT,
    raspado_em    TEXT,              -- ISO UTC "+00:00"
    busca         TSVECTOR           -- titulo + generos + sinopse; preenchida pelo reconstruir_fts.sql
);
CREATE INDEX IF NOT EXISTS idx_filmes_busca ON filmes USING GIN (busca);
