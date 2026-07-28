"""Índice de busca textual (FTS) — último passo do tratamento.

A coluna `busca` (tsvector) NÃO é gerada, porque `unaccent` não é IMMUTABLE:
quem a preenche é sql/manutencao/reconstruir_fts.sql, rodado ao fim de toda
rodada. Roda DEPOIS da curadoria, para a busca indexar o texto já corrigido.
"""

from base import conexao


def reconstruir_fts(con):
    """Sincroniza a coluna de busca textual com tratado.eventos e
    tratado.filmes."""
    con.execute(conexao.ler_sql("manutencao/reconstruir_fts.sql"))
