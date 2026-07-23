-- Recalcula a coluna de busca textual (eventos.busca, tsvector).
--
-- Rodado por store.reconstruir_fts(con) depois de cada raspagem. Pode ser rodado
-- a mao no DBeaver/psql se a busca textual parecer defasada. E um UPDATE em massa
-- de proposito: a base tem centenas de linhas e a coluna nao pode ser gerada
-- (unaccent nao e IMMUTABLE) — ver comentario da coluna em schema.sql.
--
-- local_nome e organizador entraram na v1.1 do Instagram: "o que tem no
-- Ordinario?" tem que achar evento cuja legenda so diz "Ordi" — a casa vem
-- rotulada da watchlist em local_nome, nao do texto. Vale para todas as
-- fontes ("o que tem no Culto" acha pelo local, nao so pela descricao).

UPDATE eventos SET busca = to_tsvector('pt',
    coalesce(nome, '') || ' ' || coalesce(categoria, '') || ' ' ||
    coalesce(atracoes, '') || ' ' || coalesce(descricao, '') || ' ' ||
    coalesce(local_nome, '') || ' ' || coalesce(organizador, ''));

-- Filmes em cartaz (dominio cinema, NI-07): titulo + generos bastam para a
-- busca do agente ("animacao", "terror") — sinopse nao vem da fonte.
UPDATE filmes SET busca = to_tsvector('pt',
    coalesce(titulo, '') || ' ' || coalesce(generos, ''));
