-- SCHEMA OPERACAO — as midias que NOS hospedamos (Vercel Blob): poster de
-- filme e flyer do Instagram.
--
-- POR QUE NAO FICA NO `cru`: `cru` significa "o que a fonte disse". Estas URLs
-- sao ARTEFATO PRODUZIDO POR NOS — a fonte nunca as mandou. Ficavam espalhadas
-- entre cinema_extra_raw (origem 'poster') e instagram_raw (origem 'midia'),
-- misturadas com payload de verdade.
--
-- POLITICA: **NUNCA SE DROPA**. Nao se refaz de graca — re-subir custa download
-- do CDN da fonte + upload —, e no caso do Instagram muitas vezes NAO se refaz
-- de jeito nenhum: a URL de midia do CDN expira em HORAS, entao o original pode
-- nao existir mais. INCREMENTAL: so se sobe o que ainda nao tem linha aqui.
--
-- O pathname no Blob e ESTAVEL (sem sufixo aleatorio): re-subir substitui. Sem
-- BLOB_READ_WRITE_TOKEN no ambiente, o passo e pulado e o front cai no hotlink
-- da fonte. Hosts permitidos no front: HOSTS_IMAGEM em lib/imagens.mjs.

CREATE TABLE IF NOT EXISTS operacao.midias (
    chave     TEXT NOT NULL,   -- id do dono: filmes.id ou o shortcode do post
    tipo      TEXT NOT NULL,   -- 'poster' (filme) | 'flyer' (Instagram)
    url       TEXT NOT NULL,   -- URL publica no nosso storage
    subido_em TEXT NOT NULL,   -- ISO UTC "+00:00"
    PRIMARY KEY (chave, tipo)
);
