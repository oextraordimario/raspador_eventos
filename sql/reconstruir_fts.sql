-- Reconstroi o indice de busca textual (eventos_fts) a partir da tabela eventos.
--
-- Rodado por store.reconstruir_fts(con) depois de cada raspagem, para o FTS refletir
-- as linhas novas/atualizadas. Pode ser rodado a mao no DBeaver se a busca textual
-- parecer defasada em relacao ao conteudo da tabela.

INSERT INTO eventos_fts(eventos_fts) VALUES('rebuild');
