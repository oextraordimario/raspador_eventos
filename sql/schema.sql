-- Schema da base unificada de eventos (SQLite).
--
-- Fonte da verdade do schema: este arquivo e carregado e aplicado automaticamente
-- por store.conectar() (via executescript). Tambem pode ser rodado a mao no DBeaver
-- ou no cliente sqlite3 apontando para data/eventos.db.
--
-- Idempotente: todo objeto usa "IF NOT EXISTS", entao rodar de novo nao quebra nada.

CREATE TABLE IF NOT EXISTS eventos (
    id            TEXT PRIMARY KEY,   -- "<fonte>:<id_nativo>", evita colisao entre fontes
    fonte         TEXT NOT NULL,      -- sympla | ingresse | shotgun
    id_nativo     TEXT NOT NULL,
    nome          TEXT NOT NULL,
    start_date    TEXT,               -- ISO 8601
    end_date      TEXT,               -- ISO 8601
    cidade        TEXT,
    estado        TEXT,
    local_nome    TEXT,
    endereco      TEXT,
    lat           REAL,
    lon           REAL,
    categoria     TEXT,               -- tipo/tema quando disponivel
    organizador   TEXT,
    url           TEXT,
    imagem        TEXT,
    raspado_em    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eventos_start ON eventos(start_date);
CREATE INDEX IF NOT EXISTS idx_eventos_cidade ON eventos(cidade);

-- Indice de busca textual (nome/categoria) para as consultas em linguagem natural.
-- Tabela de conteudo externo (content='eventos'): reindexada via reconstruir_fts.sql
-- apos cada raspagem.
CREATE VIRTUAL TABLE IF NOT EXISTS eventos_fts
    USING fts5(nome, categoria, content='eventos', content_rowid='rowid');
