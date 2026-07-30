"""O endereço público de cada evento e de cada filme.

`/evento/forro-na-varanda-26-07` e `/cinema/homem-aranha-um-novo-dia-2026` em
lugar de `/evento/sympla~3520331` e `/cinema/29922`. Spec:
docs/specs/20260729_urls-semanticas/.

**Por que o slug é DADO, e não cálculo na borda.** Ele podia ser montado no
front (que já tem nome e data) e recalculado no Python para achar a linha — mas
seriam duas implementações da mesma regra em duas linguagens, e a primeira
divergência entre elas não seria um título feio: seria 404. Sendo coluna, a
regra existe uma vez, a resolução é um índice, e a unicidade é garantida pelo
banco em vez de por convenção.

**Por que um passo próprio, e não dentro do `comum`.** A escada de desempate
precisa ver a tabela INTEIRA (não dá para saber se `festa-da-firma-26-07` está
livre olhando um evento só), e precisa rodar depois do `enriquecer` (para saber
quem é o canônico) e depois da `curadoria` (nome e data são curáveis à mão, e a
URL tem que refletir a correção). É o quinto ponto da ordem do `ciclo.py`.

**A escada** (a primeira forma livre ganha):

    1. titulo-dd-mm            o caso de 100% da base visível hoje
    2. titulo-dd-mm-aaaa       colisão entre ANOS (o aniversário anual da casa)
    3. titulo-dd-mm-2, -3...   colisão no MESMO DIA — hoje só entre um evento e
                               a duplicata dele, que a consulta resolve para o
                               canônico de qualquer forma

O degrau 2 só é oferecido quando o conflito é com outro ano DE VERDADE. Sem
essa checagem, duas cópias do mesmo evento no mesmo dia produziam
`aj-trio-29-07` e `aj-trio-29-07-2026` — endereço único, mas mentindo: o ano
ali sugere desambiguação de aniversário onde só havia duplicata.

**A ordem de atribuição é (dia local, canônico primeiro, não-ruído, id)**, e as
duas primeiras chaves resolvem coisas diferentes:

  * o **dia** (não o instante) mantém a propriedade que importa: evento que já
    aconteceu nunca perde o slug que tinha para um homônimo que entrou depois —
    o passado não se move, então URL antiga não é roubada;
  * **canônico primeiro** garante que o endereço limpo fique com a linha que o
    site realmente linka. Ordenar pelo instante dentro do dia parecia
    equivalente e não era: as quatro cópias de "Festa Junina | Roça N' Roll" de
    31/07 têm horas diferentes, e na primeira rodada o canônico levou
    `...-31-07-2` enquanto uma duplicata ficou com o endereço bonito.

O `nome` que entra aqui JÁ vem limpo — `comum.upsert_eventos` aplica
`texto.titulo_limpo` na escrita (NI-33). Não se limpa de novo de propósito: se
uma pessoa corrigiu o nome à mão pela curadoria, o título dela é o título, data
e tudo.
"""

from datetime import datetime, timedelta, timezone

from base import tempo, texto

# Teto do TÍTULO no slug (o sufixo de data/ano nunca é cortado). A base tem
# mediana 32 e máximo 99 chars: sem teto, o endereço do evento com nome
# quilométrico é exatamente o link com cara de spam que a spec veio consertar.
TETO_TITULO = 60

# O dia do slug é o dia LOCAL de Brasília, o mesmo que o `diaMes()` do site
# mostra na página — e NÃO o dia da vida noturna (o corte às 6h que a janela de
# período usa). A festa que começa 1h de sábado mostra "01/08" no <h1>, então
# mostra "01-08" na URL. O slug copia a tela, não a regra de janela.
BSB = timezone(timedelta(hours=-3))


def _dia_local(iso):
    """(dia ISO local, "dd-mm", "aaaa") em Brasília; três None se não parseia."""
    dt = tempo.instante(iso)
    if dt is None:
        return None, None, None
    d = dt.astimezone(BSB).date()
    return d.isoformat(), f"{d.day:02d}-{d.month:02d}", f"{d.year}"


def _base(linha, campo):
    """O pedaço-título do slug. Nome sem nenhum caractere aproveitável (só
    emoji) cai no id: endereço feio é melhor que evento sem endereço."""
    return (texto.slugificar(linha[campo], teto=TETO_TITULO)
            or texto.slugificar(linha["id"]))


def _preparar_evento(linha):
    dia, dia_mes, ano = _dia_local(linha["start_date"])
    base = _base(linha, "nome")
    linkavel = bool(linha["dedupe_canonico"] and not linha["ruido"])
    return {"id": linha["id"],
            "alvo": f"{base}-{dia_mes}" if dia_mes else base,
            # `marca` é o que o degrau 2 usa para desempatar, e só faz sentido
            # se o conflito for com um ano diferente
            "marca": ano,
            # canônico ANTES da duplicata, no mesmo dia: o endereço limpo tem
            # que ficar com a linha que o site linka
            "ordem": (dia or "", 0 if linha["dedupe_canonico"] else 1,
                      linha["ruido"] or 0, linha["id"]),
            "linkavel": linkavel}


def _preparar_filme(linha):
    """Sem `ano` (o TMDB não casou), o slug do filme fica só com o título — e
    `consulta.sessoes_filme` aceita o slug curto quando o ano aparecer depois,
    para o link compartilhado não morrer."""
    base = _base(linha, "titulo")
    return {"id": linha["id"],
            "alvo": f"{base}-{linha['ano']}" if linha["ano"] else base,
            "marca": None,   # o ano já está no alvo; nada a acrescentar
            "ordem": (linha["id"],),
            "linkavel": True}   # todo filme em cartaz tem card no site


def _escolher(item, usados):
    """O slug deste item. Devolve (slug, desempatou).

    `desempatou` marca o degrau 3 (o ordinal). Ele só chega ao relatório quando
    o item é LINKÁVEL: duplicata levando `-2` é o desenho funcionando (ela tem
    o mesmo nome no mesmo dia, e a consulta manda quem chegar nela para o
    canônico), e imprimir as 28 de hoje toda rodada treinaria a gente a ignorar
    o aviso. Canônico levando `-2`, aí sim, é sintoma — de dedupe frouxo ou de
    teto de comprimento agressivo —, e sintoma silencioso é o que esta base já
    pagou caro para aprender a não ter.
    """
    alvo, marca = item["alvo"], item["marca"]
    if alvo not in usados:
        return alvo, False
    if marca and usados[alvo] != marca and f"{alvo}-{marca}" not in usados:
        return f"{alvo}-{marca}", False
    n = 2
    while f"{alvo}-{n}" in usados:
        n += 1
    return f"{alvo}-{n}", True


def _registrar_historico(con, entidade, atribuidos):
    """Guarda em `operacao.slugs` todo endereço atribuído — é o que faz o link
    compartilhado sobreviver a um renome (2,3% dos eventos, §7.3 da spec).

    A chave é o SLUG: um endereço nunca troca de dono por acidente. O
    `registro_id` é atualizado no conflito de propósito — se a escada
    reatribuir um slug, o histórico tem que apontar para o dono atual, senão o
    308 mandaria a pessoa para o lugar errado.
    """
    agora = datetime.now(timezone.utc).isoformat()
    con.cursor().executemany(
        "INSERT INTO operacao.slugs (slug, entidade, registro_id, visto_em) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (slug) DO UPDATE SET "
        "registro_id = excluded.registro_id, visto_em = excluded.visto_em",
        [(s, entidade, rid, agora) for s, rid in atribuidos])


def _atribuir(con, tabela, sql, preparar):
    """Reatribui o slug de uma tabela inteira. Devolve (quantos, desempates).

    O `SET slug = NULL` antes não é zelo: o índice é ÚNICO, e reatribuir sem
    limpar quebraria no meio do caminho toda vez que dois registros trocassem
    de slug entre si. Ninguém enxerga o NULL — isto roda dentro da transação do
    ciclo, e o MVCC entrega o estado anterior até o commit.

    A ordem é decidida AQUI, em Python, e não por `ORDER BY`: a chave é o dia
    LOCAL de Brasília, que o SQL não tem (as colunas são ISO UTC) — e ordenar
    pelo instante em vez do dia é exatamente o bug que a docstring do módulo
    conta. A chave termina no `id`, então é total: sem isso a ordem do Postgres
    decidiria, e o slug mudaria de rodada em rodada sem nada mudar na base.
    """
    con.execute(f"UPDATE {tabela} SET slug = NULL")
    itens = sorted((preparar(l) for l in con.execute(sql).fetchall()),
                   key=lambda i: i["ordem"])
    usados, novos, desempates = {}, [], []
    for item in itens:
        s, desempatou = _escolher(item, usados)
        usados[s] = item["marca"]
        novos.append((s, item["id"]))
        if desempatou and item["linkavel"]:
            desempates.append({"id": item["id"], "slug": s})
    if novos:
        con.cursor().executemany(
            f"UPDATE {tabela} SET slug = %s WHERE id = %s", novos)
        _registrar_historico(con, tabela.split(".")[-1], novos)
    return len(novos), desempates


def aplicar(con):
    """Reatribui os endereços públicos. A seco, idempotente, não comita."""
    n_ev, desemp_ev = _atribuir(
        con, "tratado.eventos",
        "SELECT id, nome, start_date, dedupe_canonico, ruido "
        "FROM tratado.eventos", _preparar_evento)
    n_fi, desemp_fi = _atribuir(
        con, "tratado.filmes",
        "SELECT id, titulo, ano FROM tratado.filmes", _preparar_filme)
    return {"eventos": n_ev, "filmes": n_fi,
            "desempates": desemp_ev + desemp_fi}


# Quem LÊ o histórico é a `consulta.py`, pela view `public.slugs_antigos` — não
# há função de leitura aqui de propósito: a consulta importar este módulo
# arrastaria o grafo de import das cinco fontes para o runtime da API e do MCP.
