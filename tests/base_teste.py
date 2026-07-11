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
        con.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
