-- CAMADA CURADO — a referência canônica de casas e locais.
--
-- É REFERÊNCIA, não override: não corrige um registro específico, descreve uma
-- entidade do mundo. Consumida pelo TRATAMENTO (dedupe, conciliação Instagram ↔
-- plataforma) e pela COLETA (o filtro `_do_df` do Ticket and Go, que decide se
-- um evento é de Brasília sem ter endereço nenhum).
--
-- POLITICA: **NUNCA SE DROPA**. É trabalho humano acumulado.
--
-- Reúne o que estava espalhado em três lugares que não se falavam:
--   dados/locais_df.yaml       a lista que ancorava o recorte DF do TnG
--   local_aliases da watchlist as grafias que o dedupe canoniza
--   local_nome cru de cada fonte
--
-- ⚠️ MUDAR ESTA TABELA NÃO RECUPERA O PASSADO A SECO. O recorte de escopo roda
-- na COLETA, por decisão consciente de custo (spec §6.7): incluir uma casa nova
-- aqui só traz os eventos dela na próxima raspagem. Procedimento: mexeu na
-- lista, rode o Ticket and Go (~3 min).
--
-- `aliases` é TEXT[] e não tabela filha: a cardinalidade é de 0 a 3 por local,
-- e uma tabela de junção seria custo de schema sem consulta que a justifique.

CREATE TABLE IF NOT EXISTS curado.locais (
    id            TEXT PRIMARY KEY,             -- slug canônico: 'culto-rock-bar'
    nome          TEXT NOT NULL,                -- nome canônico de exibição
    aliases       TEXT[] NOT NULL DEFAULT '{}', -- como as fontes escrevem
    no_df         BOOLEAN NOT NULL DEFAULT TRUE,-- ancora o recorte do Ticket and Go
    instagram     TEXT,                         -- @ do perfil, quando há
    observacao    TEXT,
    autor         TEXT NOT NULL,
    criado_em     TEXT NOT NULL,                -- ISO UTC "+00:00"
    atualizado_em TEXT
);
