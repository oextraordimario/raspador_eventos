-- SCHEMA OPERACAO — telemetria do pipeline. Ver o cabecalho de execucoes.sql
-- para a politica da camada (**NUNCA SE DROPA**).
--
-- Uma linha por FONTE por rodada: quando a coleta daquela fonte comecou, quanto
-- ela trouxe e se falhou. Parece redundante com execucoes.fontes (o mesmo dado
-- em JSON), e nao e: aqui ele e CONSULTAVEL EM SQL, e e disso que o
-- `tratamento/sumido.py` depende.
--
-- POR QUE ELA EXISTE. `tratado.eventos.sumido` marca o evento futuro que nao
-- reapareceu no catalogo da fonte. A ancora correta e o INICIO DA COLETA daquela
-- fonte — e ate 2026-07-28 esse instante so existia como variavel local do
-- atualizar.py, o que obrigava `sumido` a ser calculado no meio da orquestracao
-- da coleta. A regra ingenua que dispensaria esta tabela (comparar o raspado_em
-- do evento com o MAIOR raspado_em da fonte) foi medida e acerta 43 de 381: o
-- raspado_em varia dentro da mesma rodada, evento a evento.
--
-- Com o instante registrado aqui, `sumido` vira derivacao a seco a partir do
-- cru + operacao, e a guarda do NI-59 ("coleta zerada nao e catalogo vazio")
-- vira `WHERE coletados > 0` em vez de um `if` no orquestrador.
-- Spec: docs/specs/20260728_arquitetura-medalhao/ §8.1.

CREATE TABLE IF NOT EXISTS operacao.coletas (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte        TEXT NOT NULL,   -- sympla | ingresse | zig | shotgun | ticketandgo | cinema | instagram
    iniciada_em  TEXT NOT NULL,   -- ISO UTC do INICIO da coleta desta fonte — a ancora do `sumido`
    terminada_em TEXT,            -- ISO UTC do fim (nulo se o processo morreu no meio)
    coletados    INTEGER,         -- itens que a fonte devolveu nesta rodada (0 e diferente de NULL: ver NI-59)
    total_site   INTEGER,         -- total que a fonte declara ter no recorte (cobertura)
    erro         TEXT             -- "Tipo: mensagem" quando a fonte falhou; NULL = sucesso
);

-- O acesso e sempre "a ultima coleta boa desta fonte" (DISTINCT ON).
CREATE INDEX IF NOT EXISTS idx_coletas_fonte
    ON operacao.coletas (fonte, iniciada_em DESC);
