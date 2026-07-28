-- CAMADA TRATADO (prata) — o schema unificado que as seis fontes viram depois
-- de normalizadas. E a tabela central do projeto.
--
-- POLITICA DE RECUPERACAO: descartavel POR DESENHO — tem que se reconstruir a
-- seco a partir do cru. (Ainda nao se reconstroi de verdade: e exatamente o
-- NI-55, resolvido na fatia 5/7 da spec 20260728_arquitetura-medalhao. Ate la,
-- tratar como se NAO fosse descartavel.)
--
-- DATAS (start_date/end_date/raspado_em): colunas TEXT com INVARIANTE — o
-- upsert normaliza tudo para ISO UTC "+00:00" (tempo.norm_ts) antes de gravar,
-- entao comparacao e ordenacao LEXICAIS sao seguras. Nao gravar data nessas
-- colunas fora do upsert sem normalizar.

CREATE TABLE IF NOT EXISTS tratado.eventos (
    id            TEXT PRIMARY KEY,   -- chave unica "<fonte>:<id_nativo>", evita colisao entre fontes
    fonte         TEXT NOT NULL,      -- plataforma de origem: sympla | ingresse | shotgun | zig | ticketandgo | instagram
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

    -- Campos ricos da fonte. Podem chegar depois do catalogo (passo incremental
    -- "descrever" do atualizar.py); por isso o upsert usa COALESCE nestas
    -- colunas: re-raspagem do catalogo NAO zera o que ja foi colhido.
    -- ATENCAO: COALESCE so protege contra valor novo NULL. `categoria` entrou
    -- nessa lista em 2026-07-28 e so funciona porque o catalogo do Sympla
    -- passou a mandar categoria NULL (event_type era 'NORMAL' em 100% dos
    -- eventos e destruia a categoria boa a cada rodada — spec §6.2).
    descricao     TEXT,               -- texto livre do evento, limpo de HTML (insumo do FTS e do enriquecimento v2)
    atracoes      TEXT,               -- line-up ("; "-separado) quando a fonte entrega (Shotgun: performer)
    preco_min     DOUBLE PRECISION,   -- menor preco de lote PAGO, em R$ total (gratis nao conta — ver tem_gratis); derivado da tabela lotes

    -- Colunas derivadas do cru (preenchidas por src/derivar.py apos o upsert;
    -- os scrapers nao escrevem aqui — exceto preco_min, que o Shotgun ainda
    -- grava e a derivacao recalcula por cima). Recalculadas do zero a cada
    -- atualizacao. Specs: 20260710_camada-bronze e 20260710_camada-prata.
    bairro        TEXT,               -- bairro do local (Sympla: location.neighborhood do payload bruto)
    popularidade  INTEGER,            -- score de trending da fonte (Sympla: global_score) — quanto maior, mais quente
    esgotado      INTEGER,            -- 1 = sem ingressos disponiveis (tickets/offers); NULL = fonte nao informou
    cancelado     INTEGER,            -- 1 = evento cancelado na origem; a consulta esconde por padrao
    tem_gratis    INTEGER,            -- 1 = ha lote gratis NAO esgotado (cortesia etc.); com preco_min NULL = evento gratis; NULL = sem info de lotes

    -- Marcada por atualizar._marcar_sumidos apos cada raspagem BEM-SUCEDIDA da
    -- fonte: evento FUTURO cujo raspado_em ficou para tras nao reapareceu no
    -- catalogo — provavel remocao/cancelamento silencioso. A consulta esconde
    -- por padrao (marcar, nao apagar). Evento passado nunca e marcado (catalogo
    -- so lista futuros). Fonte que coletou ZERO fica de fora (NI-59).
    -- Spec: docs/specs/20260710_alinhamento-constituicao/spec.md.
    sumido        INTEGER NOT NULL DEFAULT 0,

    -- Colunas de enriquecimento v1 (preenchidas por src/enriquecer.py apos o
    -- upsert; os scrapers nao escrevem aqui). Recalculadas do zero a cada rodada.
    ruido           INTEGER NOT NULL DEFAULT 0,  -- 1 = nao e vida noturna (anuncio/curso/etc.); a consulta esconde
    ruido_motivo    TEXT,                        -- regra que marcou (a palavra-chave), para auditoria
    dedupe_grupo    TEXT,                        -- id do grupo de duplicatas cross-fonte (= id do evento canonico); NULL = sem duplicata
    dedupe_canonico INTEGER NOT NULL DEFAULT 1,  -- 1 = registro que representa o grupo na consulta

    -- Indice de busca textual (nome/categoria/atracoes/descricao +
    -- local_nome/organizador — "o que tem no Ordinario?" acha pela casa) para
    -- as consultas em linguagem natural. NAO e coluna gerada (unaccent nao e
    -- IMMUTABLE): quem a preenche e sql/manutencao/reconstruir_fts.sql, chamado
    -- por store.reconstruir_fts(con) ao fim de toda rodada.
    busca         TSVECTOR
);

CREATE INDEX IF NOT EXISTS idx_eventos_start ON tratado.eventos(start_date);
CREATE INDEX IF NOT EXISTS idx_eventos_cidade ON tratado.eventos(cidade);
CREATE INDEX IF NOT EXISTS idx_eventos_busca ON tratado.eventos USING GIN (busca);
