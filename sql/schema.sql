-- Schema da base unificada de eventos (SQLite).
--
-- Fonte da verdade do schema: este arquivo e carregado e aplicado automaticamente
-- por store.conectar() (via executescript). Tambem pode ser rodado a mao no DBeaver
-- ou no cliente sqlite3 apontando para data/eventos.db.
--
-- Idempotente: todo objeto usa "IF NOT EXISTS", entao rodar de novo nao quebra nada.
--
-- Descricoes de coluna: SQLite nao tem COMMENT ON / COMMENT inline como Postgres/MySQL.
-- A forma idiomatica sao os comentarios "--" abaixo, que o SQLite preserva verbatim em
-- sqlite_master.sql -- visiveis no DDL (DBeaver: aba DDL; cli: .schema). Como a tabela
-- so guarda o CREATE de quando foi criada, alterar estas descricoes exige recriar a
-- tabela para o banco ja existente refletir a mudanca.

CREATE TABLE IF NOT EXISTS eventos (
    id            TEXT PRIMARY KEY,   -- chave unica "<fonte>:<id_nativo>", evita colisao entre fontes
    fonte         TEXT NOT NULL,      -- plataforma de origem: sympla | ingresse | shotgun
    id_nativo     TEXT NOT NULL,      -- id do evento na plataforma de origem
    nome          TEXT NOT NULL,      -- titulo do evento
    start_date    TEXT,               -- inicio, ISO 8601 (formatos mistos entre fontes; normalizar antes de comparar)
    end_date      TEXT,               -- fim, ISO 8601 (as vezes inconsistente na origem; filtrar por start_date)
    cidade        TEXT,               -- cidade (no Shotgun vem do parametro de busca, nao do dado bruto)
    estado        TEXT,               -- UF (ex.: DF)
    local_nome    TEXT,               -- nome do local / casa de festa
    endereco      TEXT,               -- endereco textual do local
    lat           REAL,               -- latitude (quando disponivel)
    lon           REAL,               -- longitude (quando disponivel)
    categoria     TEXT,               -- tipo/tema informado pela fonte (quando disponivel)
    organizador   TEXT,               -- produtor/organizador do evento
    url           TEXT,               -- link do evento na plataforma de origem
    imagem        TEXT,               -- URL da imagem / capa do evento
    raspado_em    TEXT NOT NULL,      -- timestamp ISO 8601 de quando foi raspado

    -- Campos ricos da fonte (Etapa 5 da spec da Fase 0). Podem chegar depois do
    -- catalogo (passo incremental "descrever" do atualizar.py); por isso o upsert
    -- usa COALESCE nestas colunas: re-raspagem do catalogo NAO zera o que ja foi colhido.
    descricao     TEXT,               -- texto livre do evento, limpo de HTML (insumo do FTS e do enriquecimento v2)
    atracoes      TEXT,               -- line-up ("; "-separado) quando a fonte entrega (Shotgun: performer)
    preco_min     REAL,               -- menor preco anunciado, quando a fonte entrega (Shotgun: offers)

    -- Colunas de enriquecimento v1 (preenchidas por src/enriquecer.py apos o upsert;
    -- os scrapers nao escrevem aqui). Recalculadas do zero a cada atualizacao.
    ruido           INTEGER NOT NULL DEFAULT 0,  -- 1 = nao e vida noturna (anuncio/curso/etc.); a consulta esconde
    ruido_motivo    TEXT,                        -- regra que marcou (a palavra-chave), para auditoria
    dedupe_grupo    TEXT,                        -- id do grupo de duplicatas cross-fonte (= id do evento canonico); NULL = sem duplicata
    dedupe_canonico INTEGER NOT NULL DEFAULT 1   -- 1 = registro que representa o grupo na consulta
);

CREATE INDEX IF NOT EXISTS idx_eventos_start ON eventos(start_date);
CREATE INDEX IF NOT EXISTS idx_eventos_cidade ON eventos(cidade);

-- Indice de busca textual (nome/categoria/atracoes/descricao) para as consultas em
-- linguagem natural. Tabela de conteudo externo (content='eventos'): reindexada via
-- reconstruir_fts.sql apos cada raspagem. A descricao entrou no indice na Etapa 5
-- (validado que "eletronica" passa a achar evento sem o genero no nome, sem degradar
-- as consultas canonicas — ver docs/specs/20260709_mvp-fase-0/execucao.md).
CREATE VIRTUAL TABLE IF NOT EXISTS eventos_fts
    USING fts5(nome, categoria, atracoes, descricao,
               content='eventos', content_rowid='rowid');
