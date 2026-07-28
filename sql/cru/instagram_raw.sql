-- CAMADA CRU (bronze) do Instagram: posts e stories crus dos perfis da
-- watchlist (dados/perfis_instagram.yaml), via Monid/TikHub, + o JSON extraido
-- do flyer por visao (origem 'extracao' — incremental: 1 extracao por post,
-- nunca refeita).
--
-- POLITICA DE RECUPERACAO: **NUNCA SE DROPA**. Ao contrario do cinema, NAO ha
-- poda: a tabela ACUMULA rodada a rodada (post que sai da 1a pagina do perfil
-- continua aqui — e dele que o evento deriva). Ultimo vence.
--
-- A Prata do Instagram e a propria tabela de eventos: derivar.aplicar_instagram
-- reconstroi os eventos fonte='instagram' do zero a partir daqui (post +
-- extracao). Spec: 20260723_instagram-como-fonte.
--
-- ATENCAO: a URL de midia do CDN expira em HORAS. A midia e baixada na hora da
-- ingestao (midias/instagram/, gitignorado); a URL do CDN nunca vai para a base.

CREATE TABLE IF NOT EXISTS instagram_raw (
    perfil     TEXT NOT NULL,   -- @ da watchlist (sem arroba)
    code       TEXT NOT NULL,   -- shortcode do post/story (instagram.com/p/<code>/)
    origem     TEXT NOT NULL,   -- 'post' | 'story' | 'extracao' | 'midia'
    payload    TEXT NOT NULL,   -- JSON bruto (post/story) ou JSON extraido do flyer
    raspado_em TEXT NOT NULL,   -- ISO UTC "+00:00"
    PRIMARY KEY (code, origem)
);
