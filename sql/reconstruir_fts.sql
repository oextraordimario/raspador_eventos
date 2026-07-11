-- Recalcula a coluna de busca textual (eventos.busca, tsvector) a partir dos
-- mesmos 4 campos que o FTS5 indexava na era SQLite.
--
-- Rodado por store.reconstruir_fts(con) depois de cada raspagem. Pode ser rodado
-- a mao no DBeaver/psql se a busca textual parecer defasada. E um UPDATE em massa
-- de proposito: a base tem centenas de linhas e a coluna nao pode ser gerada
-- (unaccent nao e IMMUTABLE) — ver comentario da coluna em schema.sql.

UPDATE eventos SET busca = to_tsvector('pt',
    coalesce(nome, '') || ' ' || coalesce(categoria, '') || ' ' ||
    coalesce(atracoes, '') || ' ' || coalesce(descricao, ''));

-- Filmes em cartaz (dominio cinema, NI-07): titulo + generos bastam para a
-- busca do agente ("animacao", "terror") — sinopse nao vem da fonte.
UPDATE filmes SET busca = to_tsvector('pt',
    coalesce(titulo, '') || ' ' || coalesce(generos, ''));
