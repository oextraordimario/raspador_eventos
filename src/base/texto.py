"""Limpeza de texto vinda da fonte — infra transversal, sem regra de negócio.

Mora em `base/` porque os DOIS estágios precisam: a coleta usa `limpar_html`
antes de procurar CEP na descrição do Ticket and Go (a tag `<a href>` casaria
"\\bdf\\b" dentro do atributo), e o tratamento usa a mesma função para produzir
`tratado.eventos.descricao`. Até 2026-07-28 eram quatro cópias idênticas, uma
por scraper.
"""

import html
import re


def limpar_html(texto):
    """HTML → texto puro: tags viram espaço, entidades resolvidas, espaços
    colapsados. Devolve None para vazio (inclusive para o `<p><br></p>` que o
    Zig manda como "descrição")."""
    if not texto:
        return None
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    return re.sub(r"\s+", " ", texto).strip() or None


def mesmo_nome(a, b):
    """Confere se dois nomes de evento são o mesmo (caixa/espaços à parte).

    Proteção contra id trocado (NI-17): o BFF do Sympla devolve um evento
    VÁLIDO de outro namespace (Bileto) — e às vezes de URL comum — sem erro
    HTTP; sem esta checagem, descrição e categoria alheias entram caladas na
    base. Aceita relação de prefixo (até 20 chars) nos dois sentidos porque a
    página pode usar um nome mais curto que o catálogo ("DOMINGÃO" vs
    "DOMINGÃO | PARTE 2" — caso real de 2026-07-10). Calibrada no spike da
    Bronze (tests/spike_bronze/) + primeira rodada em produção.

    Roda DUAS vezes, de propósito, e em estágios diferentes: a coleta a usa
    para não gravar payload suspeito no cru, e o tratamento para não deixar um
    payload suspeito que já esteja lá sobrescrever dado bom (§6.3).
    """
    na, nb = (re.sub(r"\s+", " ", (s or "").casefold()).strip() for s in (a, b))
    if not na or not nb:
        return False
    return na.startswith(nb[:20]) or nb.startswith(na[:20])
