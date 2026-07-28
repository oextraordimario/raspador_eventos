"""Prepara a base DESCARTÁVEL dos testes: o banco eventos_teste no Neon.

Substitui o redirecionamento para arquivo temporário da era SQLite: aponta o
store para EVENTOS_DB_URL_TESTE e recria o schema do zero (o esvaziamento que
o tempfile dava de graça). A guarda de nome garante que um teste jamais rode
na base de produção por omissão — sem a variável, o teste aborta com instrução.
"""

import sys

import psycopg

import store


def preparar():
    """Chamar antes de qualquer store.conectar() (exige src/ já no sys.path)."""
    url = store.env_var("EVENTOS_DB_URL_TESTE")
    if not url or "teste" not in url:
        sys.exit("Defina EVENTOS_DB_URL_TESTE (connection string do banco "
                 "eventos_teste no Neon) no ambiente ou no .env da raiz.\n"
                 "Os testes recriam o schema DO ZERO — por isso nunca aceitam "
                 "a base de produção (a URL precisa conter 'teste').")
    store.DB_URL = url
    with psycopg.connect(url, autocommit=True) as con:
        # Os SEIS schemas, não só `public` (spec 20260728_arquitetura-medalhao).
        # Aqui dropar é seguro e desejado — é o banco descartável, e a guarda de
        # nome acima garante que nunca é o de produção, onde `cru`/`curado`/
        # `operacao`/`uso` NUNCA se dropam.
        con.execute("DROP SCHEMA IF EXISTS cru, tratado, curado, operacao, uso "
                    "CASCADE; DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        # O DDL é aplicado AQUI, e não no primeiro store.conectar(): desde
        # 2026-07-28 conectar() não aplica schema por padrão (spec
        # 20260728_arquitetura-medalhao, D9). Os testes continuam chamando
        # store.conectar() sem argumento — é este preparar() que garante que
        # existe schema para eles encontrarem.
        con.execute(store.ddl())
