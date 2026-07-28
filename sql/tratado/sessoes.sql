-- CAMADA TRATADO (prata) do dominio CINEMA: os horarios. Reconstruida do zero
-- junto com filmes a cada rodada (SNAPSHOT — o sessionId so e estavel dentro da
-- grade corrente, entao nao ha upsert, nem dedupe, nem coluna `sumido`).
--
-- POLITICA DE RECUPERACAO: 100% descartavel.
--
-- Sem FK para filmes (mesmo padrao de lotes -> eventos): as duas tabelas sao
-- reconstruidas juntas pela derivacao, que e quem garante a consistencia.

CREATE TABLE IF NOT EXISTS tratado.sessoes (
    id         TEXT PRIMARY KEY,  -- sessionId da Ingresso.com (estavel so dentro da grade)
    filme_id   TEXT NOT NULL,     -- filmes.id
    cinema     TEXT NOT NULL,     -- apelido canonico (scrapers/cinema.py CINEMAS)
    cinema_id  TEXT NOT NULL,     -- theaterId da Ingresso.com
    inicio     TEXT NOT NULL,     -- ISO UTC "+00:00" via tempo.norm_ts (a fonte manda local -03:00)
    sala       TEXT,
    tipos      TEXT,              -- "3D/XD/Dublado" — cru de proposito, quem interpreta e o agente
    preco      DOUBLE PRECISION,  -- R$ (NULL = fonte nao informou)
    url_compra TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessoes_inicio ON tratado.sessoes(inicio);
CREATE INDEX IF NOT EXISTS idx_sessoes_filme ON tratado.sessoes(filme_id);
