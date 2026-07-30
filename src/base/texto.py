"""Limpeza de texto vinda da fonte — infra transversal, sem regra de negócio.

Mora em `base/` porque os DOIS estágios precisam: a coleta usa `limpar_html`
antes de procurar CEP na descrição do Ticket and Go (a tag `<a href>` casaria
"\\bdf\\b" dentro do atributo), e o tratamento usa a mesma função para produzir
`tratado.eventos.descricao`. Até 2026-07-28 eram quatro cópias idênticas, uma
por scraper.

`titulo_limpo` e `slugificar` chegaram em 2026-07-29 com as URLs semânticas
(spec 20260729_urls-semanticas). Elas ficam aqui, e não no tratamento, porque
nenhuma das duas conhece o domínio: quem decide QUE campos entram no endereço
público é `tratamento/slug.py`.
"""

import html
import re
import unicodedata


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


# ── Título limpo (NI-33) ───────────────────────────────────────────────────
#
# O organizador enfia a data no nome do evento: "Forró na Varanda | 28.07 |
# Varanda do Contexto". Isso rouba as duas linhas do card, repete o que a
# coluna do dia já diz e some com o nome de verdade — e, desde as URLs
# semânticas, produziria "forro-na-varanda-28-07-varanda-do-contexto-28-07".
#
# A regra é deliberadamente CONSERVADORA: só remove um trecho de data quando
# ele está ISOLADO por um separador. É o que impede de estragar "Rock dos
# 80/90", "Baile 24/7" ou "Aniversário 10/10 anos" — na dúvida, não mexe.
#
# Esta é a porta de 2026-07-29 do NI-33: a regra nasceu em `lib/formato.js`
# (2026-07-27) e consertava só o site; agora mora na escrita da prata, então o
# agente do MCP recebe o mesmo título que o site — e o slug não pode divergir
# do <h1>, porque os dois saem desta string.
_DIA_MES = (r"(?:0?[1-9]|[12]\d|3[01])\s*[/.\-]\s*(?:0?[1-9]|1[0-2])"
            r"(?:\s*[/.\-]\s*(?:\d{2}|\d{4}))?")
_SEP = r"[|–—\-·]"
# Só os separadores FORTES quebram em segmentos: partir no hífen estragaria
# "Pop-Rock", que não é separador nenhum. O grupo é de CAPTURA porque o
# separador do autor é preservado na remontagem — ver titulo_limpo.
_SEGMENTOS = re.compile(r"\s*([|–—])\s*")
_SO_DATA = re.compile(rf"^\s*{_DIA_MES}\s*$")
_DATA_CERCADA = re.compile(rf"\s*{_SEP}\s*{_DIA_MES}\s*(?={_SEP}|$)")
_DATA_NO_COMECO = re.compile(rf"^\s*{_DIA_MES}\s*{_SEP}\s*")
_SEP_ORFAO = re.compile(rf"^\s*{_SEP}\s*|\s*{_SEP}\s*$")


def _sem_segmento_de_data(nome):
    """Descarta os segmentos que são APENAS data, PRESERVANDO o separador que o
    autor usou entre os que ficam.

    A versão original (`lib/formato.js`) remontava tudo com " | " fixo, o que
    era invisível enquanto a regra servia só à exibição. Ao virar dado — que é
    o NI-33 —, o atalho apareceu na medição: dos 125 nomes que a primeira
    rodada alterou, a maioria não tinha data nenhuma; era travessão virando
    barra ("Bernardo Rosa Trio — O melhor do Pop Rock"). Trocar a tipografia do
    organizador não é limpar título, é estragar dado — e ia junto para o FTS e
    para o MCP.
    """
    partes = _SEGMENTOS.split(nome)
    segmentos, separadores = partes[0::2], partes[1::2]
    # (segmento mantido, separador que vinha logo depois dele no original)
    mantidos = [(s, separadores[i] if i < len(separadores) else None)
                for i, s in enumerate(segmentos) if not _SO_DATA.match(s)]
    if not mantidos:
        return ""
    t = mantidos[0][0]
    for anterior, (seg, _) in zip(mantidos, mantidos[1:]):
        # o separador do vizinho da esquerda — se um segmento de data caiu no
        # meio, é o que estava entre o mantido e a data que sumiu
        t += f" {anterior[1] or '|'} {seg}"
    return t


def titulo_limpo(nome):
    """Nome do evento sem a data que o organizador repetiu nele.

    Devolve o original quando a regra não acha nada — e também quando ela
    acharia TUDO (nome que é só uma data): título vazio é pior que título com
    data, e é o único caso em que a regra desiste de propósito.
    """
    if not nome:
        return nome
    t = _sem_segmento_de_data(nome)    # segmentos que são só data
    t = _DATA_CERCADA.sub(" ", t)      # data cercada por separador no meio/fim
    t = _DATA_NO_COMECO.sub("", t)     # "28/07 - Festa da Firma"
    t = _SEP_ORFAO.sub("", t)          # separador órfão nas pontas
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t or nome


def slugificar(s, teto=None):
    """Texto → pedaço de URL: sem acento, minúsculo, só [a-z0-9-].

    `teto` corta no comprimento pedido, recuando até a fronteira de palavra
    (mesma regra do trecho de descrição em api/dados.py: só recua se sobrar
    mais da metade, senão corta seco). Devolve "" para entrada que não tem
    nenhum caractere aproveitável — quem chama decide o fallback, porque só ele
    sabe qual identificador usar no lugar.
    """
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if teto and len(s) > teto:
        s = s[:teto]
        recuo = s.rfind("-")
        s = s[:recuo] if recuo > teto // 2 else s
    return s.strip("-")
