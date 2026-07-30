"""O ciclo de tratamento inteiro, numa transação só.

Reconstrói `tratado` a partir de `cru` + `curado` + `operacao`, sem tocar em
rede. É o "não raspa, só re-deriva" do `--so-derivar`, e é também o segundo
tempo de toda rodada normal.

**POR QUE UMA TRANSAÇÃO SÓ.** `public` é view sobre `tratado`, então o site e o
MCP continuam consultando enquanto isto roda. Com um commit por passo existiria
uma janela de segundos em que `tratado.eventos` está vazia e o site serve
"nenhum evento encontrado". Com uma transação só, o MVCC entrega o estado
anterior até o instante do commit.

**POR QUE `DELETE` E NÃO `TRUNCATE`.** No Postgres o `TRUNCATE` é transacional,
mas toma `ACCESS EXCLUSIVE`: os leitores BLOQUEIAM até o commit em vez de
enxergar a versão anterior. A diferença é invisível em desenvolvimento e visível
em produção. Nenhum passo daqui pode usar TRUNCATE.

**A ORDEM importa em cinco pontos, e só neles:**
  1. `instagram` depois de `comum`, que apaga `tratado.lotes` inteira (o lote
     sintético do flyer é reinserido depois);
  2. `enriquecer` depois de TODAS as fontes — o dedupe é cross-fonte, e é ele
     que concilia Instagram ↔ plataforma;
  3. `curadoria` depois do `enriquecer` (precisa poder derrubar uma decisão
     dele, como desfazer um dedupe errado) e antes do FTS;
  4. `slug` depois da `curadoria` (nome e start_date são curáveis, e o endereço
     público tem que refletir a correção humana) e depois do `enriquecer` (a
     escada de desempate dá o slug limpo ao canônico) — e também depois do
     `cinema`, de onde sai o `ano` do filme;
  5. `busca` por último, para indexar o texto já corrigido.
Entre si, as cinco trilhas de plataforma são independentes.

Specs: docs/specs/20260728_arquitetura-medalhao/ §8.1 e
docs/specs/20260729_urls-semanticas/ §3.4.
"""

from tratamento import (busca, cinema, comum, curadoria, enriquecer, instagram,
                        slug, sumido)


def executar(con, so_enriquecer=False):
    """Roda o ciclo e comita UMA vez. Retorna o que o relatório precisa.

    `so_enriquecer=True` pula a reconstrução a partir do cru e reaplica só as
    regras (ruído, dedupe, curadoria, FTS) — é o `--so-enriquecer`, atalho para
    calibrar heurística sem re-derivar 500 eventos.
    """
    from coleta import instagram as coleta_instagram

    derivado = insta = cine = sumidos = None
    if not so_enriquecer:
        derivado = comum.aplicar(con)
        insta = instagram.aplicar(con)
        cine = cinema.aplicar(con)
        sumidos = sumido.aplicar(con)

    # Os aliases de local vêm de DUAS origens que se somam, e a distinção é a
    # que mantém a camada curado honesta: a watchlist é configuração de ENTRADA
    # (muda o que se raspa) e continua em YAML versionado; `curado.locais` é
    # referência sobre entidades do mundo, curada continuamente. Spec §4.3.
    aliases = {**coleta_instagram.aliases_local(),
               **curadoria.locais_canonicos(con)}
    enriq = enriquecer.aplicar(con, aliases_local=aliases)
    cur = curadoria.aplicar(con)
    slugs = slug.aplicar(con)
    busca.reconstruir_fts(con)
    con.commit()
    return {"derivado": derivado, "instagram": insta, "cinema": cine,
            "sumidos": sumidos, "enriquecimento": enriq, "curadoria": cur,
            "slugs": slugs}
