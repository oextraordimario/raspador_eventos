"""Base de dados unificada de eventos (SQLite).

Schema unico que serve as tres fontes (Sympla, Ingresse, Shotgun). O scraper
de cada fonte normaliza para este formato antes de gravar. A base e otimizada
para consulta por texto/data/cidade, que e o que um agente de IA precisa.

O DDL vive em sql/schema.sql (fonte unica, tambem rodavel no DBeaver); este
modulo so o carrega e aplica.
"""

import json
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
    """Insere ou atualiza uma lista de eventos normalizados (dicts).

    A chave reservada "_raw" (payload bruto que o _normalizar do scraper
    recebeu) não é coluna de eventos: vai para eventos_raw como origem
    'catalogo' (camada Bronze). Dicts sem "_raw" seguem funcionando.
    """
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
    for e in eventos:
        if e.get("_raw") is not None:
            gravar_raw(con, e["id"], "catalogo", e["_raw"], e["raspado_em"],
                       commit=False)
    con.commit()
    return len(eventos)


def registrar_execucao(con, iniciada_em, duracao_s, modo, fontes, passos, erros):
    """Grava o resumo de uma rodada do atualizar.py (observabilidade, NI-19).

    fontes/passos/erros são estruturas Python; viram JSON aqui.
    """
    con.execute(
        "INSERT INTO execucoes (iniciada_em, duracao_s, modo, fontes, passos, "
        "erros) VALUES (?, ?, ?, ?, ?, ?)",
        (iniciada_em, duracao_s, modo,
         *(json.dumps(x, ensure_ascii=False) for x in (fontes, passos, erros))))
    con.commit()


def ultima_execucao(con):
    """Última rodada registrada (dict com fontes/passos/erros já desserializados)
    ou None. É a base da comparação 'vs. rodada anterior' do relatório."""
    r = con.execute("SELECT * FROM execucoes ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("fontes", "passos", "erros"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def gravar_raw(con, evento_id, origem, payload, raspado_em, commit=True):
    """Guarda o payload bruto de um evento na camada Bronze (último vence)."""
    con.execute(
        "INSERT INTO eventos_raw (evento_id, origem, payload, raspado_em) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(evento_id, origem) DO UPDATE SET "
        "payload = excluded.payload, raspado_em = excluded.raspado_em",
        (evento_id, origem, json.dumps(payload, ensure_ascii=False), raspado_em))
    if commit:
        con.commit()
