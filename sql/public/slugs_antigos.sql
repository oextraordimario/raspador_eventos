-- Contrato de consumo do HISTORICO de enderecos (spec 20260729_urls-semanticas
-- §7.3). A tabela mora em `operacao` (artefato nosso, nao se reconstroi do cru);
-- esta view e o que a camada de consulta ve.
--
-- POR QUE UMA VIEW, e nao um SELECT direto na tabela: `consulta.py` le SO
-- `public` — e a regra que mantem o contrato de consumo desacoplado do formato
-- armazenado. A alternativa era a consulta importar `tratamento/slug.py`, o que
-- arrastaria o grafo de import das cinco fontes para dentro do runtime da API e
-- do MCP por causa de um SELECT.
--
-- A view SO mostra endereco cujo registro AINDA EXISTE: historico apontando
-- para evento que saiu da base tem que virar 404, nao um 308 para o nada. E por
-- isso que o filtro esta aqui e nao em quem chama — esquecer o JOIN seria um
-- redirecionamento para pagina inexistente, que e pior que o 404 honesto.

CREATE OR REPLACE VIEW public.slugs_antigos AS
SELECT h.slug, h.entidade, h.registro_id, h.visto_em
  FROM operacao.slugs h
  JOIN tratado.eventos e ON h.entidade = 'eventos' AND e.id = h.registro_id
UNION ALL
SELECT h.slug, h.entidade, h.registro_id, h.visto_em
  FROM operacao.slugs h
  JOIN tratado.filmes f ON h.entidade = 'filmes' AND f.id = h.registro_id;
