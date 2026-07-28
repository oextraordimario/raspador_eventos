-- CAMADA CURADO — o que uma PESSOA decidiu sobre dado que já foi tratado.
--
-- POR QUE EXISTE: o tratamento é automático e reescreve `tratado` inteiro a
-- cada rodada. Qualquer correção feita direto lá — consertar um nome no
-- DBeaver, por exemplo — é APAGADA na rodada seguinte, sem aviso. Esta tabela
-- é onde a decisão humana vive FORA do que se reconstrói, para ser REAPLICADA
-- como último passo do tratamento.
--
-- POLITICA: **NUNCA SE DROPA** e **APPEND-ONLY**. Revogar preenche
-- `revogada_em`; nunca se apaga linha. Histórico de decisão humana é tão
-- insubstituível quanto dado bruto — e mais caro de refazer.
--
-- `motivo` é NOT NULL de propósito. A explicação do que mudou, quando e por
-- quê não é metadado opcional: é o PRODUTO da curadoria. Correção sem motivo
-- vira mistério em três meses, e aí ninguém tem coragem de removê-la.
--
-- `valores` é JSONB e não coluna por campo: uma tabela serve todas as
-- entidades, e caso novo não exige DDL novo. QUAIS campos são curáveis é uma
-- allowlist em CÓDIGO (tratamento/curadoria.py) — `id`, `fonte` e `busca`
-- nunca são.
--
-- `valores_antes` detecta correção OBSOLETA: se o valor atual em `tratado` já
-- não é o que era quando se corrigiu, a fonte provavelmente consertou sozinha,
-- e o relatório aponta em vez de mascarar dado bom para sempre.

CREATE TABLE IF NOT EXISTS curado.correcoes (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entidade      TEXT  NOT NULL,   -- 'eventos' | 'filmes'
    registro_id   TEXT  NOT NULL,   -- tratado.<entidade>.id
    valores       JSONB NOT NULL,   -- só o que muda: {"nome": "...", "ruido": 1}
    valores_antes JSONB,            -- o que estava lá quando se corrigiu
    motivo        TEXT  NOT NULL,   -- POR QUÊ — obrigatório, não é comentário
    autor         TEXT  NOT NULL,
    criado_em     TEXT  NOT NULL,   -- ISO UTC "+00:00"
    revogada_em   TEXT              -- NULL = ativa; correção não se apaga
);
CREATE INDEX IF NOT EXISTS idx_correcoes_alvo
    ON curado.correcoes (entidade, registro_id) WHERE revogada_em IS NULL;
