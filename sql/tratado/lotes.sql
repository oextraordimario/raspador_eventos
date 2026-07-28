-- CAMADA TRATADO (prata): lotes de ingresso por evento, extraidos dos payloads
-- do cru por src/derivar.py.
--
-- POLITICA DE RECUPERACAO: 100% descartavel e ja e reconstruida do zero a cada
-- aplicar() (DELETE + INSERT — por isso sem PK natural). E o exemplo mais limpo
-- do que "prata" significa: ser consumida pelo site nao a torna ouro; ser
-- reconstruivel a torna prata.
--
-- preco = TOTAL a pagar em R$ (Sympla ja embute a taxa; Ingresse soma
-- price+tax; Ticket and Go manda taxa_conveniencia como FRACAO — 0.1 = 10%).
-- O nome do lote fica CRU de proposito: a condicao ("CORTESIA FEMININA ATE
-- 00H", "meia-entrada") e para o agente ler, nao para regex.
-- Spec: docs/specs/20260710_lotes-ingressos/spec.md.

CREATE TABLE IF NOT EXISTS lotes (
    evento_id  TEXT NOT NULL,      -- eventos.id ("<fonte>:<id_nativo>")
    ordem      INTEGER NOT NULL,   -- posicao no payload (ordem de exibicao da fonte)
    nome       TEXT,               -- nome cru do lote na fonte
    preco      DOUBLE PRECISION,   -- R$ total a pagar (com taxa); 0 = gratis; NULL = fonte nao informou
    taxa       DOUBLE PRECISION,   -- parcela de taxa, quando a fonte separa (NULL no Shotgun)
    gratis     INTEGER NOT NULL,   -- 1 = lote gratuito (cortesia/entrada franca)
    esgotado   INTEGER             -- 1 = lote sem estoque / vendas encerradas
);
CREATE INDEX IF NOT EXISTS idx_lotes_evento ON lotes(evento_id);
