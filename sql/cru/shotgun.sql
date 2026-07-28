-- CAMADA CRU (bronze) — SHOTGUN. Mesmo esqueleto e mesma politica do
-- cru/sympla.sql — o cabecalho la explica cada coluna.
--
-- COLUNAS PROPRIAS, e elas sao o motivo de a tabela ser por fonte: o Shotgun
-- recebe cidade/estado de FORA do payload. O `addressLocality` do JSON-LD traz
-- o BAIRRO ("Asa Sul"), nao a cidade; a cidade sai do parametro de busca da
-- coleta. Sem estas colunas, a reconstrucao teria que deduzir por convencao
-- ("o recorte e Brasilia, entao...") — era o ponto de atencao nº 1 do NI-55.
-- Aqui o dado que a coleta CONHECE fica gravado, nao deduzido.
--
-- `id_nativo` E o slug do evento (a chave e "shotgun:<slug>"), entao nao ha
-- coluna `slug` separada — seria a mesma informacao duas vezes.
--
-- So a origem 'catalogo': o JSON-LD da pagina ja traz descricao, atracoes,
-- organizador e precos. O Shotgun nao passa por descrever/precificar.

CREATE TABLE IF NOT EXISTS cru.shotgun (
    id_nativo     TEXT NOT NULL,   -- o slug do evento, SEM o prefixo "shotgun:"
    origem        TEXT NOT NULL,   -- 'catalogo' (o JSON-LD traz tudo)
    raspado_em    TEXT NOT NULL,
    hash          TEXT NOT NULL,
    payload       TEXT NOT NULL,
    api           TEXT,
    cidade_label  TEXT,            -- rotulo da coleta, NAO vem do payload
    estado_label  TEXT,            -- idem
    PRIMARY KEY (id_nativo, origem, raspado_em)
);
