-- Extensoes e configuracao de busca textual. Roda ANTES de qualquer tabela:
-- os indices GIN sobre `busca` dependem da configuracao `pt` existir.

CREATE EXTENSION IF NOT EXISTS unaccent;

-- Config de busca 'pt': unaccent + stemming portugues. Preserva a insensibilidade
-- a acento que o FTS5 (unicode61) dava de graca ("eletronica" acha "eletrônica")
-- e adiciona stemming ("festas" acha "festa"). Se o stemming degradar as
-- consultas canonicas, o fallback documentado na spec e copiar de 'simple'.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'pt') THEN
        CREATE TEXT SEARCH CONFIGURATION pt (COPY = portuguese);
        ALTER TEXT SEARCH CONFIGURATION pt
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, portuguese_stem;
    END IF;
END $$;
