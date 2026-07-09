"""Base de dados unificada de eventos (SQLite).

Schema unico que serve as tres fontes (Sympla, Ingresse, Shotgun). O scraper
de cada fonte normaliza para este formato antes de gravar. A base e otimizada
para consulta por texto/data/cidade, que e o que um agente de IA precisa.

O DDL vive em sql/schema.sql (fonte unica, tambem rodavel no DBeaver); este
modulo so o carrega e aplica.
"""

import sqlite3
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent

# A base fica em data/ na raiz do repo (um nivel acima de src/), separada do
# codigo-fonte. E gitignorada e regeravel via raspagem.
DB_PATH = _RAIZ / "data" / "eventos.db"

# SQL (schema + manutencao) mora em sql/, como fonte unica: os mesmos arquivos
# rodam a mao no DBeaver. Ver sql/schema.sql e sql/reconstruir_fts.sql.
_SQL_DIR = _RAIZ / "sql"


def _ler_sql(nome):
    return (_SQL_DIR / nome).read_text(encoding="utf-8")


def reconstruir_fts(con):
    """Sincroniza o indice de busca textual com a tabela eventos."""
    con.executescript(_ler_sql("reconstruir_fts.sql"))
    con.commit()


def conectar():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(_ler_sql("schema.sql"))
    return con


# Campos ricos que podem ser colhidos num passo separado do catalogo (o "descrever"
# do atualizar.py): no upsert, valor novo NULL preserva o que ja esta na base.
_COLS_PRESERVAR = {"descricao", "atracoes", "preco_min"}


def upsert_eventos(con, eventos):
    """Insere ou atualiza uma lista de eventos normalizados (dicts)."""
    cols = ["id", "fonte", "id_nativo", "nome", "start_date", "end_date",
            "cidade", "estado", "local_nome", "endereco", "lat", "lon",
            "categoria", "organizador", "url", "imagem", "raspado_em",
            "descricao", "atracoes", "preco_min"]
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(
        f"{c}=COALESCE(excluded.{c}, {c})" if c in _COLS_PRESERVAR
        else f"{c}=excluded.{c}"
        for c in cols if c != "id")
    sql = (f"INSERT INTO eventos ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    con.executemany(sql, [[e.get(c) for c in cols] for e in eventos])
    con.commit()
    return len(eventos)
