-- CAMADA CRU (bronze) do cinema: payload bruto por cinema x dia, ultimo vence.
--
-- POLITICA DE RECUPERACAO: nao se dropa, mas e a UNICA bronze com PODA por
-- desenho — dias que ficaram no passado saem na raspagem. A grade da semana
-- passada nao tem consulta que a justifique, e histórico custaria 20 KB x 64
-- por rodada para responder pergunta que ninguem faz. Decisao explicita da
-- spec 20260711_raspagem-cinema; nao e inconsistencia herdada.
--
-- Cinema x dia ausente de uma rodada (falha de rede) MANTEM o payload anterior:
-- buraco nao apaga grade boa. 404 da fonte = dia sem sessao, nao e erro.

CREATE TABLE IF NOT EXISTS cru.cinema (
    cinema_id  TEXT NOT NULL,   -- theaterId da Ingresso.com
    dia        TEXT NOT NULL,   -- dia da grade "YYYY-MM-DD" (data LOCAL de Brasilia, como a API pagina)
    payload    TEXT NOT NULL,   -- JSON bruto (json.dumps ensure_ascii=False)
    raspado_em TEXT NOT NULL,   -- ISO UTC "+00:00"
    PRIMARY KEY (cinema_id, dia)
);
