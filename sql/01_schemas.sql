-- Os schemas, que sao a fronteira FISICA entre as camadas do medalhao.
--
-- Ate 2026-07-28 tudo convivia em `public` e a fronteira entre as camadas era
-- convencao verbal. Sem fronteira fisica, "idempotente" e uma promessa que nada
-- obriga a cumprir — e a consequencia foi medida, nao teorica (spec
-- 20260728_arquitetura-medalhao §6).
--
-- A REGRA DE RECUPERACAO CABE NUMA LINHA, e e o motivo de os schemas existirem:
--
--     cru, curado, operacao e uso NUNCA se dropam.
--     tratado e public SEMPRE se reconstroem.
--
-- O criterio e sempre o mesmo: **o que nao se pode refazer sozinho nao se
-- dropa.** `cru` porque a fonte nao devolve o passado; `curado` porque e
-- trabalho humano; `operacao`/`uso` porque registram o que aconteceu uma vez.
-- Foi a falta disso que custou o catalogo inteiro do Shotgun em 2026-07-27.

CREATE SCHEMA IF NOT EXISTS cru;       -- bronze: o que a fonte disse
CREATE SCHEMA IF NOT EXISTS tratado;   -- prata: unificado, derivado, enriquecido
CREATE SCHEMA IF NOT EXISTS curado;    -- o que uma PESSOA decidiu
CREATE SCHEMA IF NOT EXISTS operacao;  -- telemetria do pipeline e artefatos nossos
CREATE SCHEMA IF NOT EXISTS uso;       -- quem usou — DADO DE PESSOA (LGPD)

-- `public` nao e criado aqui (ja existe) e nao ganha tabela nenhuma: vira
-- contrato de consumo, so com as views de sql/public/.

COMMENT ON SCHEMA cru      IS 'Bronze — payload como a fonte mandou. NUNCA SE DROPA.';
COMMENT ON SCHEMA tratado  IS 'Prata — reconstruivel a seco a partir de cru. Descartavel.';
COMMENT ON SCHEMA curado   IS 'Decisao humana sobre dado ja tratado. NUNCA SE DROPA.';
COMMENT ON SCHEMA operacao IS 'Telemetria do pipeline e artefatos proprios. NUNCA SE DROPA.';
COMMENT ON SCHEMA uso      IS 'Dado de pessoa (LGPD). NUNCA SE DROPA.';
