-- Contrato de consumo do domínio CINEMA (NI-07). 1:1 com tratado.filmes.

CREATE OR REPLACE VIEW public.filmes AS
SELECT id, titulo, titulo_original, generos, duracao_min, classificacao,
       distribuidora, url, poster, poster_proprio, trailer, em_pre_venda,
       sinopse, ano, nota, votos, tmdb_id, raspado_em, busca
FROM tratado.filmes;
