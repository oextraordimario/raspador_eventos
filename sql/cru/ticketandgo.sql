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

-- Mudanca ADITIVA (fatia 7): `visto_em` = a ultima vez que ESTE payload foi
-- visto identico na fonte, e nao a vez em que ele MUDOU.
--
-- POR QUE ELA PRECISA EXISTIR. O append-only nao grava versao nova quando o
-- payload nao mudou — entao `raspado_em` e a data da ultima MUDANCA. Usa-lo
-- como ancora do `sumido` marcaria como "sumiu do catalogo" todo evento que
-- simplesmente nao mudou desde a rodada passada. `visto_em` avanca em toda
-- coleta, sem custar linha nova, e e ele que vira tratado.eventos.raspado_em.
--
-- O `CREATE TABLE IF NOT EXISTS` acima nao altera tabela que ja existe: por
-- isso o ALTER ao lado. O UPDATE e o backfill unico das linhas anteriores a
-- coluna (idempotente — depois da primeira vez nao casa nenhuma linha).
ALTER TABLE cru.ticketandgo ADD COLUMN IF NOT EXISTS visto_em TEXT;
UPDATE cru.ticketandgo SET visto_em = raspado_em WHERE visto_em IS NULL;
