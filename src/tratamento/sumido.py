"""Derivação de `tratado.eventos.sumido` a partir de `operacao.coletas`.

Evento FUTURO cujo `raspado_em` ficou atrás do início da última coleta boa da
fonte não reapareceu no catálogo — provável remoção ou cancelamento silencioso,
que o payload não avisa. Marcar, não apagar: quem esconde é a consulta.

Era `atualizar._marcar_sumidos`, no meio da orquestração da coleta, porque o
instante de início de cada fonte só existia como variável local. Com
`operacao.coletas` (spec §8.1) virou derivação a seco: `--so-derivar` reproduz
esta coluna como reproduz as outras.

TRÊS GUARDAS, e nenhuma é `if` de orquestração — todas saem do SQL:

1. **Fonte que falhou não condena seus eventos** (`erro IS NULL`). Um 500 do
   Sympla não pode esconder a agenda inteira dele.
2. **Fonte que coletou ZERO também não** (`coletados > 0`, NI-59). O Shotgun
   devolveu 0 COM sucesso por três rodadas no CI e escondeu a própria agenda.
   Catálogo de plataforma de ingresso não esvazia de um dia para o outro;
   quando esvazia de verdade, os eventos morrem por data passada.
3. **Instagram e cinema ficam fora.** Por construção a coleta dos dois não
   registra linha aqui — mas a lista `FORA` repete a guarda de propósito, em
   cinturão e suspensório: se alguém um dia passar a registrar (por
   uniformidade, com a melhor das intenções), a agenda inteira do Instagram
   sumiria da consulta em silêncio. Post que sai da 1ª página do perfil não
   significa cancelamento — evento do Instagram morre por data passada —, e
   sessão de cinema é snapshot, sem id estável entre semanas.

Evento PASSADO nunca é marcado: o catálogo só lista futuros, e marcá-lo
apagaria o histórico da consulta.

Specs: 20260710_alinhamento-constituicao, 20260728_fontes-quebradas §3.3.
"""

from base import tempo

# Fontes cujo "não apareceu na coleta" NÃO significa "saiu do catálogo".
FORA = ("instagram", "cinema")


def ultima_coleta_boa(con):
    """{fonte: iniciada_em} da última coleta bem-sucedida e não-vazia."""
    return {r["fonte"]: r["iniciada_em"] for r in con.execute(
        "SELECT DISTINCT ON (fonte) fonte, iniciada_em FROM operacao.coletas "
        "WHERE erro IS NULL AND coletados > 0 AND fonte <> ALL(%s) "
        "ORDER BY fonte, iniciada_em DESC", (list(FORA),))}


def aplicar(con):
    """Recalcula `sumido` para toda fonte com coleta boa registrada.

    Idempotente (quem reapareceu é desmarcado no mesmo comando) e a seco. NÃO
    comita — quem comita é `tratamento/ciclo.py`.

    Retorna a lista [(nome, fonte)] dos marcados, para o relatório.
    """
    marcados = []
    for fonte, iniciada_em in ultima_coleta_boa(con).items():
        inicio = tempo.norm_ts(iniciada_em)
        if not inicio:
            continue
        # Comparação LEXICAL: start_date/raspado_em obedecem ao invariante de
        # ISO UTC "+00:00" (garantido pelo upsert), e `inicio` passa pelo mesmo
        # norm_ts. `raspado_em IS NULL` não existe (coluna NOT NULL), mas a
        # comparação com NULL devolveria NULL e o CASE cairia no ELSE 0 —
        # errar para o lado de NÃO esconder.
        cur = con.execute(
            "UPDATE tratado.eventos SET sumido = CASE "
            "  WHEN start_date >= %s AND raspado_em < %s THEN 1 ELSE 0 END "
            "WHERE fonte = %s", (inicio, inicio, fonte))
        if not cur.rowcount:
            continue
        marcados.extend(
            (r["nome"], fonte) for r in con.execute(
                "SELECT nome FROM tratado.eventos "
                "WHERE fonte = %s AND sumido = 1", (fonte,)))
    return marcados
