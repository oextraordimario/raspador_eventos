"""Base de dados unificada de eventos (Postgres gerenciado no Neon — Fase 0b).

Schema unico que serve as tres fontes (Sympla, Ingresse, Shotgun). O scraper
de cada fonte normaliza para este formato antes de gravar. A base e otimizada
para consulta por texto/data/cidade, que e o que um agente de IA precisa — e
vive na nuvem para a consulta funcionar com o PC do autor desligado.

O DDL vive em sql/schema.sql (fonte unica, tambem rodavel no DBeaver); este
modulo so o carrega e aplica. A connection string vem de EVENTOS_DB_URL
(variavel de ambiente, com fallback no .env da raiz — parser proprio de 5
linhas em vez de dependencia). Spec: docs/specs/20260711_consulta-na-nuvem/.
"""

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

import tempo

_RAIZ = Path(__file__).resolve().parent.parent

# SQL (schema + manutencao) mora em sql/, como fonte unica: os mesmos arquivos
# rodam a mao no DBeaver/psql. Ver sql/schema.sql e sql/reconstruir_fts.sql.
_SQL_DIR = _RAIZ / "sql"

# Override para os testes (tests/ apontam para o banco eventos_teste ANTES de
# qualquer conectar()); None = resolve EVENTOS_DB_URL do ambiente/.env.
DB_URL = None

# Colunas de data normalizadas na escrita (invariante do schema: ISO UTC
# "+00:00", via tempo.norm_ts) — e o que torna a comparacao lexical segura
# sem a funcao SQL norm_ts que o SQLite registrava em runtime.
_COLS_DATA = {"start_date", "end_date", "raspado_em"}


def env_var(nome):
    """Le uma variavel do ambiente, com fallback no .env da raiz do repo."""
    if nome in os.environ:
        return os.environ[nome]
    arq = _RAIZ / ".env"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            chave, sep, valor = linha.partition("=")
            if sep and chave.strip() == nome:
                return valor.strip()
    return None


def _ler_sql(nome):
    return (_SQL_DIR / nome).read_text(encoding="utf-8")


def reconstruir_fts(con):
    """Sincroniza a coluna de busca textual (tsvector) com a tabela eventos."""
    con.execute(_ler_sql("reconstruir_fts.sql"))
    con.commit()


def conectar():
    url = DB_URL or env_var("EVENTOS_DB_URL")
    if not url:
        sys.exit("EVENTOS_DB_URL nao definida. Configure a connection string do "
                 "Neon (banco eventos) como variavel de ambiente ou no .env da "
                 "raiz do repo.")
    con = psycopg.connect(url, row_factory=dict_row)
    con.execute(_ler_sql("schema.sql"))
    con.commit()
    return con


# Campos ricos que podem ser colhidos num passo separado do catalogo (o "descrever"
# do atualizar.py): no upsert, valor novo NULL preserva o que ja esta na base.
_COLS_PRESERVAR = {"descricao", "atracoes", "preco_min"}


def upsert_eventos(con, eventos):
    """Insere ou atualiza uma lista de eventos normalizados (dicts).

    As colunas de data passam por tempo.norm_ts aqui — e o unico ponto de
    escrita, entao e ele que garante o invariante do schema (ISO UTC "+00:00",
    comparavel lexicalmente).

    A chave reservada "_raw" (payload bruto que o _normalizar do scraper
    recebeu) não é coluna de eventos: vai para eventos_raw como origem
    'catalogo' (camada Bronze). Dicts sem "_raw" seguem funcionando.
    """
    cols = ["id", "fonte", "id_nativo", "nome", "start_date", "end_date",
            "cidade", "estado", "local_nome", "endereco", "lat", "lon",
            "categoria", "organizador", "url", "imagem", "raspado_em",
            "descricao", "atracoes", "preco_min"]
    placeholders = ",".join("%s" for _ in cols)
    updates = ",".join(
        f"{c}=COALESCE(excluded.{c}, eventos.{c})" if c in _COLS_PRESERVAR
        else f"{c}=excluded.{c}"
        for c in cols if c != "id")
    sql = (f"INSERT INTO eventos ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    con.cursor().executemany(sql, [
        [tempo.norm_ts(e.get(c)) if c in _COLS_DATA else e.get(c) for c in cols]
        for e in eventos])
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
        "erros) VALUES (%s, %s, %s, %s, %s, %s)",
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
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(evento_id, origem) DO UPDATE SET "
        "payload = excluded.payload, raspado_em = excluded.raspado_em",
        (evento_id, origem, json.dumps(payload, ensure_ascii=False), raspado_em))
    if commit:
        con.commit()


def gravar_cinema_raw(con, itens, raspado_em):
    """Grava a grade bruta do cinema na Bronze (cinema_raw, último vence) e
    poda os dias que já ficaram no passado — o snapshot da grade corrente é o
    único com valor de consulta. Cinema×dia ausente de `itens` (falha de rede
    na raspagem) mantém o payload anterior. Spec: 20260711_raspagem-cinema.
    """
    if itens:
        con.cursor().executemany(
            "INSERT INTO cinema_raw (cinema_id, dia, payload, raspado_em) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT(cinema_id, dia) DO UPDATE SET "
            "payload = excluded.payload, raspado_em = excluded.raspado_em",
            [(cid, dia, json.dumps(payload, ensure_ascii=False), raspado_em)
             for cid, dia, payload in itens])
        con.execute("DELETE FROM cinema_raw WHERE dia < %s",
                    (min(dia for _, dia, _ in itens),))
    con.commit()
    return len(itens)
