-- Schema da base unificada de eventos (Postgres gerenciado no Neon — Fase 0b).
--
-- Fonte da verdade do schema: este arquivo e carregado e aplicado automaticamente
-- por store.conectar() (idempotente: IF NOT EXISTS; a config de busca `pt` via
-- bloco DO). Tambem pode ser rodado a mao no DBeaver/psql apontando para o banco.
--
-- DATAS (start_date/end_date/raspado_em): colunas TEXT com INVARIANTE — o
-- store.upsert_eventos normaliza tudo para ISO UTC "+00:00" (tempo.norm_ts)
-- antes de gravar, entao comparacao e ordenacao LEXICAIS sao seguras. Nao gravar
-- data nessas colunas fora do upsert sem normalizar.
--
-- Base descartavel (convencao da Fase 0, sem migracoes): mudou o schema?
--   DROP SCHEMA public CASCADE; CREATE SCHEMA public;
-- no banco `eventos` e re-raspe (python src/atualizar.py --precificar-tudo).
--
-- Spec da migracao SQLite -> Postgres: docs/specs/20260711_consulta-na-nuvem/.

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

CREATE TABLE IF NOT EXISTS eventos (
    id            TEXT PRIMARY KEY,   -- chave unica "<fonte>:<id_nativo>", evita colisao entre fontes
    fonte         TEXT NOT NULL,      -- plataforma de origem: sympla | ingresse | shotgun
    id_nativo     TEXT NOT NULL,      -- id do evento na plataforma de origem
    nome          TEXT NOT NULL,      -- titulo do evento
    start_date    TEXT,               -- inicio, ISO UTC "+00:00" (normalizado no upsert — ver invariante acima)
    end_date      TEXT,               -- fim, idem (as vezes inconsistente na origem; filtrar por start_date)
    cidade        TEXT,               -- cidade (no Shotgun vem do parametro de busca, nao do dado bruto)
    estado        TEXT,               -- UF (ex.: DF)
    local_nome    TEXT,               -- nome do local / casa de festa
    endereco      TEXT,               -- endereco textual do local
    lat           DOUBLE PRECISION,   -- latitude (quando disponivel)
    lon           DOUBLE PRECISION,   -- longitude (quando disponivel)
    categoria     TEXT,               -- tipo/tema informado pela fonte (quando disponivel)
    organizador   TEXT,               -- produtor/organizador do evento
    url           TEXT,               -- link do evento na plataforma de origem
    imagem        TEXT,               -- URL da imagem / capa do evento
    raspado_em    TEXT NOT NULL,      -- ISO UTC da ultima vez que o evento apareceu na raspagem do CATALOGO da fonte
                                      -- (so o upsert do catalogo atualiza; descrever/precificar nao mexem aqui).
                                      -- E a ancora da coluna sumido — nao atualizar fora do upsert.

    -- Campos ricos da fonte (Etapa 5 da spec da Fase 0). Podem chegar depois do
    -- catalogo (passo incremental "descrever" do atualizar.py); por isso o upsert
    -- usa COALESCE nestas colunas: re-raspagem do catalogo NAO zera o que ja foi colhido.
    descricao     TEXT,               -- texto livre do evento, limpo de HTML (insumo do FTS e do enriquecimento v2)
    atracoes      TEXT,               -- line-up ("; "-separado) quando a fonte entrega (Shotgun: performer)
    preco_min     DOUBLE PRECISION,   -- menor preco de lote PAGO, em R$ total (gratis nao conta — ver tem_gratis); derivado da tabela lotes

    -- Colunas derivadas da camada Bronze (preenchidas por src/derivar.py a partir
    -- de eventos_raw, apos o upsert; os scrapers nao escrevem aqui — exceto
    -- preco_min, que o Shotgun ainda grava e a derivacao recalcula por cima).
    -- Recalculadas do zero a cada atualizacao. Specs: 20260710_camada-bronze e
    -- 20260710_camada-prata em docs/specs/.
    bairro        TEXT,               -- bairro do local (Sympla: location.neighborhood do payload bruto)
    popularidade  INTEGER,            -- score de trending da fonte (Sympla: global_score) — quanto maior, mais quente
    esgotado      INTEGER,            -- 1 = sem ingressos disponiveis (tickets/offers); NULL = fonte nao informou
    cancelado     INTEGER,            -- 1 = evento cancelado na origem; a consulta esconde por padrao
    tem_gratis    INTEGER,            -- 1 = ha lote gratis NAO esgotado (cortesia etc.); com preco_min NULL = evento gratis; NULL = sem info de lotes

    -- Marcada por atualizar._marcar_sumidos apos cada raspagem BEM-SUCEDIDA da fonte:
    -- evento FUTURO cujo raspado_em ficou para tras nao reapareceu no catalogo —
    -- provavel remocao/cancelamento silencioso. A consulta esconde por padrao
    -- (marcar, nao apagar). Evento passado nunca e marcado (catalogo so lista
    -- futuros). Spec: docs/specs/20260710_alinhamento-constituicao/spec.md.
    sumido        INTEGER NOT NULL DEFAULT 0,

    -- Colunas de enriquecimento v1 (preenchidas por src/enriquecer.py apos o upsert;
    -- os scrapers nao escrevem aqui). Recalculadas do zero a cada atualizacao.
    ruido           INTEGER NOT NULL DEFAULT 0,  -- 1 = nao e vida noturna (anuncio/curso/etc.); a consulta esconde
    ruido_motivo    TEXT,                        -- regra que marcou (a palavra-chave), para auditoria
    dedupe_grupo    TEXT,                        -- id do grupo de duplicatas cross-fonte (= id do evento canonico); NULL = sem duplicata
    dedupe_canonico INTEGER NOT NULL DEFAULT 1,  -- 1 = registro que representa o grupo na consulta

    -- Indice de busca textual (nome/categoria/atracoes/descricao) para as
    -- consultas em linguagem natural. NAO e coluna gerada (unaccent nao e
    -- IMMUTABLE): quem a preenche e sql/reconstruir_fts.sql, chamado por
    -- store.reconstruir_fts(con) ao fim de toda rodada — mesmo papel do rebuild
    -- do FTS5 na era SQLite.
    busca         TSVECTOR
);

CREATE INDEX IF NOT EXISTS idx_eventos_start ON eventos(start_date);
CREATE INDEX IF NOT EXISTS idx_eventos_cidade ON eventos(cidade);
CREATE INDEX IF NOT EXISTS idx_eventos_busca ON eventos USING GIN (busca);

-- Camada Bronze: o payload bruto (JSON/JSON-LD) de cada evento, como veio da
-- fonte. Permite re-derivar campos novos SEM re-raspar (src/derivar.py) e
-- auditar a base contra a origem. Um evento pode ter VARIOS payloads (Sympla:
-- catalogo + BFF da pagina + tickets) — por isso tabela propria com origem na
-- chave, e nao uma coluna raw em eventos. Ultimo payload vence (UPSERT na PK).
-- Spec: docs/specs/20260710_camada-bronze/spec.md.
CREATE TABLE IF NOT EXISTS eventos_raw (
    evento_id  TEXT NOT NULL,   -- eventos.id ("<fonte>:<id_nativo>")
    origem     TEXT NOT NULL,   -- qual payload: 'catalogo' | 'detalhe' | 'tickets'
    payload    TEXT NOT NULL,   -- JSON bruto (json.dumps ensure_ascii=False)
    raspado_em TEXT NOT NULL,   -- timestamp ISO 8601 de quando foi raspado
    PRIMARY KEY (evento_id, origem)
);

-- Camada Prata: lotes de ingresso por evento, extraidos dos payloads da Bronze
-- por src/derivar.py (reconstruida do zero a cada aplicar(): DELETE + INSERT,
-- por isso sem PK natural). preco = TOTAL a pagar em R$ (Sympla ja embute a
-- taxa; Ingresse soma price+tax). O nome do lote fica cru de proposito: a
-- condicao ("CORTESIA FEMININA ATE 00H", "meia-entrada") e para o agente ler,
-- nao para regex. Spec: docs/specs/20260710_lotes-ingressos/spec.md.
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

-- Observabilidade da rodada: uma linha por execucao do atualizar.py, para o
-- relatorio comparar com a rodada anterior e alertar queda de coleta (scraper
-- quebrado em silencio — a hipotese de risco nº 1 do produto). Campos compostos
-- ficam como JSON em TEXT de proposito: tabelas relacionais seriam custo de
-- schema sem consulta que o justifique (quem le e gente depurando + o proprio
-- relatorio). Spec: docs/specs/20260710_alinhamento-constituicao/spec.md.
CREATE TABLE IF NOT EXISTS execucoes (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    iniciada_em TEXT NOT NULL,   -- ISO 8601 UTC do inicio da rodada
    duracao_s   DOUBLE PRECISION, -- duracao total em segundos
    modo        TEXT NOT NULL,   -- completo | sem-shotgun | so-derivar | so-enriquecer
    fontes      TEXT,            -- JSON {fonte: {coletados, total_site} | {erro}}
    passos      TEXT,            -- JSON {descrever, precificar, derivado, ruido, dedupe_grupos, sumidos}
    erros       TEXT             -- JSON [{passo, evento_id, erro}] — falha POR EVENTO
);
