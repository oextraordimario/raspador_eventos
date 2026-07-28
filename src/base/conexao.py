"""Conexão com a base e carregamento do DDL — infra transversal, sem regra de
negócio nenhuma.

A base é Postgres gerenciado no Neon. A connection string vem de EVENTOS_DB_URL
(variável de ambiente, com fallback no .env da raiz — parser próprio de 5 linhas
em vez de dependência); os testes redirecionam para EVENTOS_DB_URL_TESTE.

O DDL vive em sql/, UM ARQUIVO POR TABELA, em pastas que anunciam a camada
(sql/cru/, sql/tratado/, sql/curado/, sql/operacao/, sql/uso/, sql/public/) —
fonte única, também rodável à mão no DBeaver; este módulo só carrega e aplica,
na ordem de _ORDEM_DDL.

Era metade do antigo src/store.py, que acumulava conexão, DDL, escrita da prata,
escrita da bronze e registro de execução — quatro estágios do pipeline no mesmo
arquivo. Specs: 20260711_consulta-na-nuvem/, 20260728_arquitetura-medalhao/.
"""

import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

_RAIZ = Path(__file__).resolve().parents[2]
_SQL_DIR = _RAIZ / "sql"

# Ordem de aplicação do DDL, fixa em CÓDIGO (nada de numerar arquivo, que
# envelhece mal): as extensões primeiro — os índices GIN sobre `busca` dependem
# da configuração de busca `pt` existir —, os schemas em seguida, depois as
# camadas na ordem em que o dado flui, e as views de `public` por último, porque
# dependem das tabelas de `tratado`. Dentro de cada pasta, ordem alfabética.
# Pasta ausente é ignorada.
_ORDEM_DDL = ("00_extensoes.sql", "01_schemas.sql", "cru", "tratado", "curado",
              "operacao", "uso", "public")

# Override para os testes (tests/ apontam para o banco eventos_teste ANTES de
# qualquer conectar()); None = resolve EVENTOS_DB_URL do ambiente/.env.
DB_URL = None


def env_var(nome):
    """Lê uma variável do ambiente, com fallback no .env da raiz do repo."""
    if nome in os.environ:
        return os.environ[nome]
    arq = _RAIZ / ".env"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            chave, sep, valor = linha.partition("=")
            if sep and chave.strip() == nome:
                return valor.strip()
    return None


def ler_sql(nome):
    """Lê um .sql de sql/ pelo caminho relativo (ex.: 'manutencao/x.sql')."""
    return (_SQL_DIR / nome).read_text(encoding="utf-8")


def arquivos_ddl():
    """Os .sql do schema, na ordem de aplicação (ver _ORDEM_DDL)."""
    for item in _ORDEM_DDL:
        alvo = _SQL_DIR / item
        if alvo.is_dir():
            yield from sorted(alvo.glob("*.sql"))
        elif alvo.is_file():
            yield alvo


def ddl():
    """Todo o DDL concatenado, para UM execute só.

    Um arquivo por tabela é bom para ler e revisar; mandar um execute por
    arquivo seria um round-trip ao Neon por arquivo, em cada conexão — e o
    pipeline abre várias conexões curtas de propósito.
    """
    return "\n\n".join(a.read_text(encoding="utf-8") for a in arquivos_ddl())


def conectar(aplicar_schema=False):
    """Abre uma conexão com a base.

    aplicar_schema=True SÓ nos entrypoints de escrita e nos testes. O DDL é
    idempotente, mas aplicá-lo em toda conexão custa um round-trip ao Neon por
    conexão — e a consulta abre uma por chamada, sem nunca precisar de DDL.
    Até 2026-07-28 toda conexão aplicava (spec 20260728_arquitetura-medalhao, D9).
    """
    url = DB_URL or env_var("EVENTOS_DB_URL")
    if not url:
        sys.exit("EVENTOS_DB_URL não definida. Configure a connection string do "
                 "Neon (banco eventos) como variável de ambiente ou no .env da "
                 "raiz do repo.")
    con = psycopg.connect(url, row_factory=dict_row)
    if aplicar_schema:
        con.execute(ddl())
        con.commit()
    return con
