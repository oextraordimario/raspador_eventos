"""Base de dados unificada de eventos (SQLite).

Schema unico que serve as tres fontes (Sympla, Ingresse, Shotgun). O scraper
de cada fonte normaliza para este formato antes de gravar. A base e otimizada
para consulta por texto/data/cidade, que e o que um agente de IA precisa.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "eventos.db"

SCHEMA = """
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

-- indice de busca textual (nome) para as consultas em linguagem natural.
-- Tabela de conteudo externo: reindexada via reconstruir_fts() apos cada raspagem.
CREATE VIRTUAL TABLE IF NOT EXISTS eventos_fts
    USING fts5(nome, categoria, content='eventos', content_rowid='rowid');
"""


def reconstruir_fts(con):
    """Sincroniza o indice de busca textual com a tabela eventos."""
    con.execute("INSERT INTO eventos_fts(eventos_fts) VALUES('rebuild')")
    con.commit()


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_eventos(con, eventos):
    """Insere ou atualiza uma lista de eventos normalizados (dicts)."""
    cols = ["id", "fonte", "id_nativo", "nome", "start_date", "end_date",
            "cidade", "estado", "local_nome", "endereco", "lat", "lon",
            "categoria", "organizador", "url", "imagem", "raspado_em"]
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    sql = (f"INSERT INTO eventos ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    con.executemany(sql, [[e.get(c) for c in cols] for e in eventos])
    con.commit()
    return len(eventos)
