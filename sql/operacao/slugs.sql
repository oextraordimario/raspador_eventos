-- SCHEMA OPERACAO — o HISTORICO de enderecos publicos ja atribuidos.
--
-- POR QUE EXISTE: 2,3% dos eventos trocam de nome durante a vida (medido no
-- historico append-only do cru em 2026-07-29: 8 de 345 eventos com 2+ versoes
-- de catalogo). Trocar de nome troca o slug, e o link que alguem mandou no
-- WhatsApp viraria 404. Aqui fica o endereco antigo apontando para o registro,
-- e a resolucao responde 308 para o endereco de hoje.
--
-- POR QUE FICA EM `operacao`, e nao em `tratado`: **nao se reconstroi do cru**.
-- O nome antigo do evento esta lá, mas a REGRA que gerou aquele slug pode nao
-- existir mais (teto de comprimento, escada de desempate, limpeza de titulo — as
-- tres mudam com o tempo). O que se perde aqui nao volta. **NUNCA SE DROPA.**
--
-- POLITICA DE ESCRITA: append-only por `slug` — o slug e a chave, entao um
-- endereco nunca "muda de dono" por acidente. O `registro_id` E atualizado no
-- conflito, e de proposito: se a escada de desempate reatribuir um slug a outro
-- registro, o historico tem que apontar para o dono ATUAL, senao o 308 mandaria
-- a pessoa para o lugar errado.
--
-- Spec: docs/specs/20260729_urls-semanticas/ §7.3.

CREATE TABLE IF NOT EXISTS operacao.slugs (
    slug        TEXT PRIMARY KEY,  -- o endereco, sem o prefixo da rota
    entidade    TEXT NOT NULL,     -- 'eventos' | 'filmes'
    registro_id TEXT NOT NULL,     -- tratado.eventos.id | tratado.filmes.id
    visto_em    TEXT NOT NULL      -- ISO UTC "+00:00" da ultima rodada que o atribuiu
);
CREATE INDEX IF NOT EXISTS idx_slugs_registro ON operacao.slugs(entidade, registro_id);
