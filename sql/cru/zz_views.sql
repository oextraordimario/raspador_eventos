-- As views "_atual": o ESTADO CORRENTE de cada fonte append-only, e o
-- inventario que o relatorio le.
--
-- O tratamento consome estas views, nao as tabelas. Quem quiser serie temporal
-- (historico de preco, rastro de mudanca na fonte) vai na tabela.
--
-- NOME DO ARQUIVO: o carregador aplica os .sql de cada pasta em ordem
-- ALFABETICA, e view sobre tabela inexistente falha. "zz_" garante que este
-- arquivo venha depois de todas as tabelas de cru/.
--
-- DISTINCT ON e do Postgres e e exatamente a operacao que se quer: a PRIMEIRA
-- linha de cada grupo depois do ORDER BY. Com raspado_em DESC, e a mais recente.

CREATE OR REPLACE VIEW cru.sympla_atual AS
SELECT DISTINCT ON (id_nativo, origem) *
FROM cru.sympla ORDER BY id_nativo, origem, raspado_em DESC;

CREATE OR REPLACE VIEW cru.ingresse_atual AS
SELECT DISTINCT ON (id_nativo, origem) *
FROM cru.ingresse ORDER BY id_nativo, origem, raspado_em DESC;

CREATE OR REPLACE VIEW cru.zig_atual AS
SELECT DISTINCT ON (id_nativo, origem) *
FROM cru.zig ORDER BY id_nativo, origem, raspado_em DESC;

CREATE OR REPLACE VIEW cru.shotgun_atual AS
SELECT DISTINCT ON (id_nativo, origem) *
FROM cru.shotgun ORDER BY id_nativo, origem, raspado_em DESC;

CREATE OR REPLACE VIEW cru.ticketandgo_atual AS
SELECT DISTINCT ON (id_nativo, origem) *
FROM cru.ticketandgo ORDER BY id_nativo, origem, raspado_em DESC;

-- Inventario: reune as CONTAGENS das fontes (nao os payloads), para o relatorio
-- de saude do pipeline. Antes era um GROUP BY numa tabela so.
CREATE OR REPLACE VIEW cru.inventario AS
     SELECT 'sympla'      AS fonte, origem, count(*) AS versoes,
            count(DISTINCT id_nativo) AS registros, max(raspado_em) AS ultima
       FROM cru.sympla GROUP BY origem
UNION ALL
     SELECT 'ingresse', origem, count(*), count(DISTINCT id_nativo), max(raspado_em)
       FROM cru.ingresse GROUP BY origem
UNION ALL
     SELECT 'zig', origem, count(*), count(DISTINCT id_nativo), max(raspado_em)
       FROM cru.zig GROUP BY origem
UNION ALL
     SELECT 'shotgun', origem, count(*), count(DISTINCT id_nativo), max(raspado_em)
       FROM cru.shotgun GROUP BY origem
UNION ALL
     SELECT 'ticketandgo', origem, count(*), count(DISTINCT id_nativo), max(raspado_em)
       FROM cru.ticketandgo GROUP BY origem
UNION ALL
     SELECT 'instagram', origem, count(*), count(DISTINCT code), max(raspado_em)
       FROM cru.instagram GROUP BY origem
UNION ALL
     SELECT 'cinema', 'grade', count(*), count(DISTINCT cinema_id), max(raspado_em)
       FROM cru.cinema
UNION ALL
     SELECT 'tmdb', 'enriquecimento', count(*), count(DISTINCT filme_id), max(raspado_em)
       FROM cru.tmdb;
