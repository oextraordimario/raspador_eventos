-- CAMADA CRU (bronze) do ENRIQUECIMENTO de cinema (NI-36/NI-37): dado que NAO
-- vem da grade — match TMDB, copia do poster no storage proprio.
--
-- POLITICA DE RECUPERACAO: **NUNCA SE DROPA**, e e ACUMULATIVA, fora do
-- snapshot de proposito: filmes/sessoes sao reconstruidas do zero a cada
-- rodada, e o enriquecimento nao pode ser re-buscado (nem se perder) por causa
-- disso. Incremental: so se busca filme que ainda nao tem linha da origem.
--
-- A origem 'poster' guarda a URL da copia no NOSSO storage (Vercel Blob), que
-- nao e payload de fonte — a fatia 3 da spec 20260728_arquitetura-medalhao a
-- move para operacao.midias, e o que sobra aqui vira cru.tmdb.

CREATE TABLE IF NOT EXISTS cru.cinema_extra (
    filme_id   TEXT NOT NULL,     -- filmes.id (id da Ingresso.com, estavel)
    origem     TEXT NOT NULL,     -- 'tmdb' | 'poster' | futuras
    payload    TEXT NOT NULL,     -- JSON bruto (candidatos + escolhido, p/ auditoria)
    raspado_em TEXT NOT NULL,     -- ISO UTC "+00:00"
    PRIMARY KEY (filme_id, origem)
);
