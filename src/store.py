"""Base de dados unificada de eventos (Postgres gerenciado no Neon — Fase 0b).

Schema unico que serve as tres fontes (Sympla, Ingresse, Shotgun). O scraper
de cada fonte normaliza para este formato antes de gravar. A base e otimizada
para consulta por texto/data/cidade, que e o que um agente de IA precisa — e
vive na nuvem para a consulta funcionar com o PC do autor desligado.

O DDL vive em sql/, UM ARQUIVO POR TABELA, em pastas que anunciam a camada
(sql/cru/, sql/tratado/, sql/operacao/, sql/uso/) — fonte unica, tambem
rodavel a mao no DBeaver; este modulo so carrega e aplica, na ordem de
_ORDEM_DDL. A connection string vem de EVENTOS_DB_URL (variavel de ambiente,
com fallback no .env da raiz — parser proprio de 5 linhas em vez de
dependencia). Specs: docs/specs/20260711_consulta-na-nuvem/ e
docs/specs/20260728_arquitetura-medalhao/.
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
# rodam a mao no DBeaver/psql.
_SQL_DIR = _RAIZ / "sql"

# Ordem de aplicacao do DDL, fixa em CODIGO (nada de numerar arquivo, que
# envelhece mal): as extensoes primeiro — os indices GIN sobre `busca` dependem
# da configuracao de busca `pt` existir —, depois as camadas na ordem em que o
# dado flui. Dentro de cada pasta, ordem alfabetica. Pasta ausente e ignorada,
# porque a estrutura cresce fatia a fatia (spec 20260728_arquitetura-medalhao).
_ORDEM_DDL = ("00_extensoes.sql", "01_schemas.sql", "cru", "tratado", "curado",
              "operacao", "uso", "public")

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


def arquivos_ddl():
    """Os .sql do schema, na ordem de aplicacao (ver _ORDEM_DDL)."""
    for item in _ORDEM_DDL:
        alvo = _SQL_DIR / item
        if alvo.is_dir():
            yield from sorted(alvo.glob("*.sql"))
        elif alvo.is_file():
            yield alvo


def ddl():
    """Todo o DDL concatenado, para UM execute so.

    Um arquivo por tabela e bom para ler e revisar; mandar um execute por
    arquivo seria um round-trip ao Neon por arquivo, em cada conexao — e o
    pipeline abre varias conexoes curtas de proposito.
    """
    return "\n\n".join(a.read_text(encoding="utf-8") for a in arquivos_ddl())


def reconstruir_fts(con):
    """Sincroniza a coluna de busca textual (tsvector) com eventos e filmes."""
    con.execute(_ler_sql("manutencao/reconstruir_fts.sql"))
    con.commit()


def conectar(aplicar_schema=False):
    """Abre uma conexao com a base.

    aplicar_schema=True SO nos entrypoints de escrita e nos testes. O DDL e
    idempotente, mas aplica-lo em toda conexao custa um round-trip ao Neon por
    conexao — e a consulta abre uma por chamada, sem nunca precisar de DDL.
    Ate 2026-07-28 toda conexao aplicava; ver spec 20260728_arquitetura-medalhao
    (D9).
    """
    url = DB_URL or env_var("EVENTOS_DB_URL")
    if not url:
        sys.exit("EVENTOS_DB_URL nao definida. Configure a connection string do "
                 "Neon (banco eventos) como variavel de ambiente ou no .env da "
                 "raiz do repo.")
    con = psycopg.connect(url, row_factory=dict_row)
    if aplicar_schema:
        con.execute(ddl())
        con.commit()
    return con


# Campos ricos que podem ser colhidos num passo separado do catalogo (o "descrever"
# do atualizar.py): no upsert, valor novo NULL preserva o que ja esta na base.
#
# `categoria` esta aqui desde 2026-07-28: o "descrever" colhe a categoria real
# do Sympla e a raspagem seguinte do catalogo a sobrescrevia. Isto so funciona
# porque o catalogo passou a mandar categoria NULL (ver sympla._normalizar) —
# COALESCE nao protege contra valor novo NAO-nulo.
_COLS_PRESERVAR = {"descricao", "atracoes", "preco_min", "categoria"}


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


def gravar_instagram_raw(con, itens, raspado_em, commit=True):
    """Grava payloads do Instagram na Bronze (instagram_raw, último vence).

    itens = [(perfil, code, origem, payload)] — origem 'post'/'story' vem da
    raspagem; 'extracao' é o JSON do flyer (1 por post, incremental). Ao
    contrário do cinema, NÃO há poda: a Bronze acumula (post que sai da 1ª
    página do perfil continua aqui — é dele que o evento deriva).
    Spec: 20260723_instagram-como-fonte.

    Post em COLABORAÇÃO entre dois perfis da watchlist chega no lote com o
    mesmo (code, origem) duas vezes — o Postgres rejeita ON CONFLICT repetido
    no mesmo comando, então o lote é deduplicado antes (o PRIMEIRO perfil do
    lote fica dono do post; o payload é o mesmo).
    """
    if itens:
        unicos = {}
        for perfil, code, origem, payload in itens:
            unicos.setdefault((code, origem), (perfil, code, origem, payload))
        con.cursor().executemany(
            "INSERT INTO instagram_raw (perfil, code, origem, payload, "
            "raspado_em) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT(code, origem) DO UPDATE SET "
            "payload = excluded.payload, raspado_em = excluded.raspado_em",
            [(perfil, code, origem, json.dumps(payload, ensure_ascii=False),
              raspado_em)
             for perfil, code, origem, payload in unicos.values()])
    if commit:
        con.commit()
    return len(itens)


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


def gravar_cinema_extra(con, filme_id, origem, payload, raspado_em):
    """Grava um enriquecimento de filme na Bronze acumulativa
    (cinema_extra_raw): match TMDB, cópia de pôster etc. Fora do snapshot de
    propósito — sobrevive à reconstrução de filmes/sessoes. Último vence
    (re-tentativa de match sobrescreve o anterior)."""
    con.execute(
        "INSERT INTO cinema_extra_raw (filme_id, origem, payload, raspado_em) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(filme_id, origem) DO UPDATE SET "
        "payload = excluded.payload, raspado_em = excluded.raspado_em",
        (filme_id, origem, json.dumps(payload, ensure_ascii=False), raspado_em))
    con.commit()
