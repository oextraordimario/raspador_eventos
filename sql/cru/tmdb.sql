-- CAMADA CRU (bronze) — TMDB. Enriquecimento de filme, nao catalogo: sinopse
-- pt-BR, nota, ano e votos por filme.
--
-- POLITICA: **NUNCA SE DROPA**, ACUMULATIVA e fora do snapshot de proposito —
-- tratado.filmes/sessoes sao reconstruidas do zero a cada rodada, e o
-- enriquecimento nao pode se perder por causa disso. INCREMENTAL: so se busca
-- filme que ainda nao tem linha aqui. Nao e append-only: a re-tentativa de um
-- match que falhou deve sobrescrever, nao acumular versao.
--
-- O payload guarda candidatos + escolhido para AUDITORIA. `escolhido` None
-- significa que o matching (titulo normalizado exato) nao confiou — o filme
-- fica sem nota, de proposito: na duvida, nao chutar.
--
-- Saiu da antiga cinema_extra_raw, que misturava isto com a URL do poster no
-- NOSSO storage — que nao e payload de fonte e foi para operacao.midias.
-- Atribuicao ao TMDB no rodape e na pagina "sobre" (exigencia dos ToS deles).

CREATE TABLE IF NOT EXISTS cru.tmdb (
    filme_id   TEXT PRIMARY KEY,  -- tratado.filmes.id (id da Ingresso.com, estavel)
    payload    TEXT NOT NULL,     -- JSON bruto (candidatos + escolhido)
    raspado_em TEXT NOT NULL      -- ISO UTC "+00:00"
);
