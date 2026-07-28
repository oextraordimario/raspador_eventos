-- Contrato de consumo dos horários de cinema. 1:1 com tratado.sessoes.

CREATE OR REPLACE VIEW public.sessoes AS
SELECT id, filme_id, cinema, cinema_id, inicio, sala, tipos, preco, url_compra
FROM tratado.sessoes;
