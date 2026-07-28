-- A FILA DA CURADORIA: o que precisa de olho humano e que hoje se perde no
-- stdout do relatório, entre centenas de linhas que ninguém relê.
--
-- É VIEW, não tabela — e isso é o desenho, não economia. Três dos quatro sinais
-- são calculáveis por JOIN, então a fila está sempre atual sem depender de o
-- tratamento ter lembrado de registrar nada, e não há tabela para manter em
-- sincronia com a realidade.
--
-- O quarto sinal (dedupe limítrofe) é o único que exige persistir algo: o
-- enriquecer calcula a similaridade e a jogava fora. Virou a coluna
-- tratado.eventos.dedupe_score, aditiva.
--
-- NOME DO ARQUIVO: "zz_" garante que a view seja aplicada depois das tabelas
-- de curado/ (o carregador vai em ordem alfabética).

CREATE OR REPLACE VIEW curado.pendencias AS

-- 1. Local fora da referência canônica. É o "candidato a locais_df.yaml" que o
--    Ticket and Go imprime no fim da raspagem e o terminal engole.
SELECT 'local-desconhecido' AS tipo,
       e.id                 AS registro_id,
       e.local_nome         AS detalhe,
       'local que não casa com nenhum curado.locais — casa recorrente merece '
       'virar linha lá, senão some calada no dia em que a descrição dela não '
       'repetir o endereço' AS porque
  FROM tratado.eventos e
 WHERE e.local_nome IS NOT NULL AND e.ruido = 0
   AND NOT EXISTS (SELECT 1 FROM curado.locais l
                    WHERE lower(l.nome) = lower(e.local_nome)
                       OR lower(e.local_nome) = ANY (
                            SELECT lower(a) FROM unnest(l.aliases) a))

UNION ALL

-- 2. Dedupe de similaridade LIMÍTROFE: quase colou com outro evento do mesmo
--    dia e não colou. Os dois lados do erro custam caro — falso positivo
--    esconde festa real, falso negativo duplica —, então a faixa cinzenta é
--    exatamente o que merece olho humano.
SELECT 'dedupe-limitrofe', e.id, e.nome,
       'similaridade de ' || round(e.dedupe_score::numeric, 2)
       || ' com outro evento do mesmo dia, abaixo do corte — conferir se são '
       'o mesmo evento'
  FROM tratado.eventos e
 WHERE e.dedupe_grupo IS NULL AND e.ruido = 0
   AND e.dedupe_score >= 0.62 AND e.dedupe_score < 0.80

UNION ALL

-- 3. Correção ÓRFÃ: o registro que ela corrigia sumiu da prata.
SELECT 'correcao-orfa', c.registro_id, c.motivo,
       'correção ativa apontando para registro que não existe mais em tratado.'
       || c.entidade
  FROM curado.correcoes c
 WHERE c.revogada_em IS NULL AND c.entidade = 'eventos'
   AND NOT EXISTS (SELECT 1 FROM tratado.eventos e WHERE e.id = c.registro_id)

UNION ALL

-- 4. Correção OBSOLETA: o valor de antes já não é o que está lá, ou seja, a
--    fonte provavelmente consertou sozinha. Sem este sinal, a correção
--    mascararia dado bom para sempre.
SELECT 'correcao-obsoleta', c.registro_id, c.motivo,
       'o valor original mudou na fonte — a correção pode ter virado '
       'desnecessária'
  FROM curado.correcoes c
  JOIN tratado.eventos e ON e.id = c.registro_id
 WHERE c.revogada_em IS NULL AND c.entidade = 'eventos'
   AND c.valores_antes IS NOT NULL
   AND EXISTS (
        SELECT 1 FROM jsonb_each_text(c.valores_antes) AS antes(k, v)
         WHERE to_jsonb(e) ->> antes.k IS DISTINCT FROM antes.v);
