-- CAMADA CRU (bronze) — TICKET AND GO. Mesmo esqueleto e mesma politica do
-- cru/sympla.sql — o cabecalho la explica cada coluna.
--
-- COLUNAS PROPRIAS: como o Shotgun, recebe cidade/estado de fora do payload —
-- a fonte NAO expoe mais endereco desde que a API V1 foi desligada, e quem
-- decide se o evento e do DF e o `_do_df` da coleta (locais curados -> termo
-- inequivoco -> CEP 70-73 / \bDF\b na descricao).
--
-- `slug` e coluna porque NAO e derivavel do id: a chave e o id NUMERICO
-- ("ticketandgo:<id>") e o slug vem em campo separado do catalogo. Nas duas
-- eras ele mora em chaves diferentes (`slug_evento` na V2, `slug` na V1) —
-- guardar o que a coleta de fato usou torna a reconstrucao independente de
-- adivinhar a forma do payload.
--
-- ERAS: 5 dos payloads de catalogo sao da API V1, desligada em 2026-07-28,
-- com schema completamente diferente (`slug`, `endereco_completo`, `latitude`).
-- O parser novo aplicado a eles NAO falha — acha `nome` e `inicio` por
-- coincidencia de nome de campo e degrada em silencio. Dai a coluna `api`.

CREATE TABLE IF NOT EXISTS cru.ticketandgo (
    id_nativo     TEXT NOT NULL,   -- id NUMERICO na fonte, SEM o prefixo "ticketandgo:"
    origem        TEXT NOT NULL,   -- 'catalogo' | 'tickets'
    raspado_em    TEXT NOT NULL,
    hash          TEXT NOT NULL,
    payload       TEXT NOT NULL,
    api           TEXT,            -- 'v1' | 'v2'; NULL = anterior ao registro
    slug          TEXT,            -- nao derivavel do id; muda de chave entre as eras
    cidade_label  TEXT,            -- rotulo da coleta, NAO vem do payload
    estado_label  TEXT,            -- idem
    PRIMARY KEY (id_nativo, origem, raspado_em)
);
