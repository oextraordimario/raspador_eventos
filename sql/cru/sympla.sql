-- CAMADA CRU (bronze) — SYMPLA. O que a fonte disse, no formato dela.
--
-- POLITICA: **NUNCA SE DROPA** e **APPEND-ONLY**. Cada coleta que traz payload
-- DIFERENTE do ultimo acrescenta uma versao; nada e apagado no lugar. Isso da
-- historico de preco (dado de produto, nao so auditoria), rastro de mudanca na
-- fonte, e reconstrucao da prata para QUALQUER data passada.
--
-- A unica excecao ao "nada e apagado" e a poda de sql/manutencao/
-- podar_historico.sql: passados JANELA_HISTORICO_DIAS, sobra so a ultima versao
-- de cada (id_nativo, origem). Nunca poda o estado atual.
--
-- `hash` = sha256 da forma CANONICA (json.dumps sort_keys=True) — a canonizacao
-- entra so no hash; o payload gravado e o que a fonte mandou, fiel. Sem
-- sort_keys, fonte que reordena chaves geraria versao nova toda rodada sem ter
-- mudado nada. A comparacao e com a ULTIMA versao, nao com "existe alguma
-- igual": um payload que vai de A para B e volta para A registra as tres
-- transicoes — o comportamento certo para um lote que esgotou e voltou.
--
-- `api` = era do endpoint, declarada pela COLETA (que sabe qual chamou). NULL =
-- anterior ao registro. Resolve por estrutura o problema de payloads de duas
-- geracoes convivendo sob a mesma origem (spec §6.3).

CREATE TABLE IF NOT EXISTS cru.sympla (
    id_nativo  TEXT NOT NULL,   -- id na fonte, SEM o prefixo "sympla:" (redundante aqui)
    origem     TEXT NOT NULL,   -- 'catalogo' | 'detalhe' | 'tickets'
    raspado_em TEXT NOT NULL,   -- ISO UTC: quando ESTA versao foi coletada
    hash       TEXT NOT NULL,   -- sha256 da forma canonica do payload
    payload    TEXT NOT NULL,   -- JSON como veio (fiel, nao canonizado)
    api        TEXT,            -- era do endpoint; NULL = anterior ao registro
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
ALTER TABLE cru.sympla ADD COLUMN IF NOT EXISTS visto_em TEXT;
UPDATE cru.sympla SET visto_em = raspado_em WHERE visto_em IS NULL;
