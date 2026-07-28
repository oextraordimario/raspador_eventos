-- SCHEMA PUBLIC — o CONTRATO DE CONSUMO do site e do MCP. Só views; nenhuma
-- tabela mora aqui (spec 20260728_arquitetura-medalhao, D3).
--
-- O ganho não é esconder linha — é DESACOPLAR o formato consumido do formato
-- armazenado. Antes, mudar uma coluna de `eventos` quebrava ao mesmo tempo a
-- derivação, a consulta, o MCP e o site. Com a view no meio, `tratado` pode
-- mudar e a view absorve.
--
-- O QUE ESTA VIEW DELIBERADAMENTE **NÃO** FAZ:
--   * filtrar ruído/cancelado/sumido — a decisão é da consulta, que precisa
--     poder mostrar os dois lados (`incluir_ruido=True` existe e serve para
--     depurar). Filtro de linha em view é regra de negócio escondida.
--   * esconder `organizador` — a omissão é postura de CANAL (página pública
--     indexável vs. MCP em contexto privado) e continua em api/dados.py.
--
-- A única coluna que fica de fora é `ruido_motivo`: é auditoria da regra que
-- marcou, para gente depurando o enriquecimento — não é dado de evento.

CREATE OR REPLACE VIEW public.eventos AS
SELECT id, fonte, id_nativo, nome, start_date, end_date, cidade, estado,
       local_nome, endereco, bairro, lat, lon, categoria, organizador, url,
       imagem, raspado_em, descricao, atracoes, preco_min, tem_gratis,
       esgotado, popularidade, cancelado, sumido, ruido, dedupe_grupo,
       dedupe_canonico, busca
FROM tratado.eventos;
