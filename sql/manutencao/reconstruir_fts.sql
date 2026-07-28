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

UPDATE tratado.eventos SET busca = to_tsvector('pt',
    coalesce(nome, '') || ' ' || coalesce(categoria, '') || ' ' ||
    coalesce(atracoes, '') || ' ' || coalesce(descricao, '') || ' ' ||
    coalesce(local_nome, '') || ' ' || coalesce(organizador, ''));

-- Filmes em cartaz (dominio cinema, NI-07): titulo + generos + sinopse (a
-- sinopse chegou com o NI-36/TMDB — "filme de robo" acha pelo texto) + o
-- titulo original ("weapons" acha o filme que aqui chama "A Hora do Mal").
UPDATE tratado.filmes SET busca = to_tsvector('pt',
    coalesce(titulo, '') || ' ' || coalesce(titulo_original, '') || ' ' ||
    coalesce(generos, '') || ' ' || coalesce(sinopse, ''));
