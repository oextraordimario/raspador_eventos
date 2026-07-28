-- CAMADA CRU (bronze) — o payload bruto (JSON/JSON-LD) de cada evento, como
-- veio da fonte. Permite re-derivar campos novos SEM re-raspar e auditar a base
-- contra a origem. Um evento pode ter VARIOS payloads (Sympla: catalogo + BFF
-- da pagina + tickets) — por isso tabela propria com origem na chave, e nao uma
-- coluna raw em eventos.
--
-- POLITICA DE RECUPERACAO: **NUNCA SE DROPA**. A fonte nao devolve o passado.
-- Foi apagar esta tabela com pressa que custou o catalogo inteiro do Shotgun em
-- 2026-07-27. Se algo destrutivo for inevitavel, exportar antes.
--
-- HOJE: ultimo payload vence (UPSERT na PK) e as cinco fontes dividem a mesma
-- tabela. A fatia 5 da spec 20260728_arquitetura-medalhao divide isto em uma
-- tabela POR FONTE e troca o upsert por append-only com dedupe por hash.
-- Specs: 20260710_camada-bronze, 20260728_arquitetura-medalhao.

CREATE TABLE IF NOT EXISTS cru.eventos_raw (
    evento_id  TEXT NOT NULL,   -- eventos.id ("<fonte>:<id_nativo>")
    origem     TEXT NOT NULL,   -- qual payload: 'catalogo' | 'detalhe' | 'tickets'
    payload    TEXT NOT NULL,   -- JSON bruto (json.dumps ensure_ascii=False)
    raspado_em TEXT NOT NULL,   -- timestamp ISO 8601 de quando foi raspado
    PRIMARY KEY (evento_id, origem)
);
