"""Enriquecimento v1 da base (regras, sem LLM): filtro de ruído + dedupe cross-fonte.

Roda depois do upsert, sobre a base inteira (centenas de linhas — custo
irrelevante). Idempotente: cada execução reseta as colunas de enriquecimento e
reaplica as regras do zero, então mudar uma regra não exige re-raspar.

Políticas (ver docs/specs/20260709_mvp-fase-0/spec.md):
- Ruído: marcar, não apagar. Na dúvida, NÃO marcar — falso positivo esconde
  festa de verdade; falso negativo é ruído tolerável.
- Dedupe: conservador. Evento sumir da resposta por dedupe errado é pior do
  que aparecer duas vezes. Âncora em data+local, não só no nome.
"""

import re
import unicodedata
from datetime import timedelta, timezone
from difflib import SequenceMatcher

from base import tempo

# O "mesmo dia" do dedupe é o dia LOCAL de Brasília (UTC-3 fixo, escopo do
# PRD), não o dia UTC: festa das 21h local cai no dia UTC seguinte, e o par
# dela sem hora (agenda do Instagram, 00:00 local) ficava em bucket diferente
# — item da agenda nunca casava com o post do dia (achado do teste da v1.1).
_FUSO_BRASILIA = timezone(timedelta(hours=-3))

# Termos que denunciam não-evento (anúncio, curso, corporativo). Casados por
# fronteira de palavra sobre o nome normalizado (sem acento/pontuação), então
# "curso" não pega "percurso" nem "aula" pega "aulão". Calibrada contra a base
# real — ao mexer, rode `python src/atualizar.py --so-enriquecer` e revise a
# lista de marcados no relatório.
RUIDO_TERMOS = [
    "curso", "cursos", "workshop", "congresso", "conferencia", "seminario",
    "simposio", "palestra", "imersao", "treinamento", "mentoria", "aula",
    "aulas", "mba", "pos graduacao", "webinar", "banda larga", "consorcio",
    "credito", "investimento", "investimentos",
    # eventos políticos (calibração 2026-07-09: "lançamento" sozinho marcaria
    # show de lançamento de álbum, que é vida noturna real; "candidatura" é preciso)
    "candidatura",
    # nome em inglês (calibração 2026-07-09: "International Conference of
    # Nanoscience..." passou porque a lista era só em português)
    "conference",
]

# Similaridade de nome (0..1) para considerar duplicata cross-fonte.
SIM_NOME_FORTE = 0.85   # nome sozinho basta
SIM_NOME_FRACA = 0.55   # exige também o mesmo local

# Duplicata INTRA-fonte (NI-01, spec instagram §8.4): regra mais apertada que
# a cross-fonte (falso positivo é mais provável — edições/lotes do mesmo
# produtor): mesmo local é OBRIGATÓRIO, além do mesmo dia. Cobre o mesmo
# evento anunciado N vezes na mesma plataforma ("DEU BENZA" 3x na Arena CCB)
# e a agenda semanal do Instagram ↔ o post individual do dia.
SIM_NOME_INTRA = 0.55

# Ordem de preferência para o canônico em caso de empate de completude
# (Sympla costuma trazer mais metadados). Instagram por último: quem vende o
# ingresso tem o dado transacional; o post entra como outras_urls do canônico.
_PREF_FONTE = {"sympla": 0, "shotgun": 1, "ingresse": 2, "zig": 3,
               "ticketandgo": 4, "instagram": 5}

# Campos cuja presença mede a "completude" de um registro (escolha do canônico).
# preco_min entrou na v1.1 do Instagram: entre a linha da agenda semanal e o
# post individual do evento (que tem o preço do flyer), o individual vence.
_CAMPOS_COMPLETUDE = ["endereco", "local_nome", "organizador", "imagem",
                      "end_date", "lat", "preco_min"]


def _normalizar_texto(s):
    """minúsculas, sem acento, sem pontuação, espaços colapsados."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


_RUIDO_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in RUIDO_TERMOS) + r")\b")


# Datas embutidas no nome ("05/07", "2026") inflam a similaridade entre eventos
# distintos do mesmo dia — removidas antes de comparar.
_DATAS_NO_NOME_RE = re.compile(r"\b\d{1,2} \d{1,2}\b|\b\d{4}\b")


def _nome_comparavel(nome):
    s = _DATAS_NO_NOME_RE.sub(" ", _normalizar_texto(nome))
    return re.sub(r"\s+", " ", s).strip()


def _sim(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _marcar_ruido(con):
    """Marca ruido=1 nos nomes que casam com RUIDO_TERMOS. Retorna [(nome, termo)]."""
    marcados = []
    for r in con.execute("SELECT id, nome FROM tratado.eventos"):
        m = _RUIDO_RE.search(_normalizar_texto(r["nome"]))
        if m:
            con.execute("UPDATE tratado.eventos SET ruido = 1, ruido_motivo = %s "
                        "WHERE id = %s", (m.group(1), r["id"]))
            marcados.append((r["nome"], m.group(1)))
    return marcados


def _e_duplicata(a, b):
    sim = _sim(a["nome_cmp"], b["nome_cmp"])
    mesmo_local = bool(a["local_cmp"]) and a["local_cmp"] == b["local_cmp"]
    if a["fonte"] != b["fonte"]:
        return sim >= SIM_NOME_FORTE or (sim >= SIM_NOME_FRACA and mesmo_local)
    # sub-eventos do MESMO post do Instagram (instagram:<code>:<n>) são
    # distintos por construção — a extração já os separou. Sem esta guarda,
    # "Samba Dona" e "Samba da Tia Zélia" no mesmo sábado do carrossel-agenda
    # colavam por similaridade (falso positivo real de 2026-07-23, que
    # escondia festa da consulta).
    if a["id"].split(":")[:2] == b["id"].split(":")[:2]:
        return False
    # mesma fonte (NI-01): local igual é obrigatório mesmo com nome idêntico
    # (séries de festas distintas do mesmo dia não podem colar pelo nome só)
    return mesmo_local and sim >= SIM_NOME_INTRA


def _agrupar_duplicatas(con, aliases_local=None):
    """Agrupa duplicatas (mesmo dia UTC + regras de similaridade) — entre
    fontes E dentro da mesma fonte (NI-01, regra apertada em _e_duplicata).

    aliases_local ({grafia: nome canônico}, tipicamente da watchlist do
    Instagram) canoniza o local ANTES de comparar: "Culto" e "Culto Rock Bar"
    passam a ser o mesmo local_cmp — é o elo da conciliação post ↔ evento de
    plataforma (spec 20260723_instagram-como-fonte §2.7).

    Retorna a lista de grupos, cada um como lista de dicts dos membros
    (canônico primeiro).
    """
    canon_local = {_normalizar_texto(a): _normalizar_texto(nome)
                   for a, nome in (aliases_local or {}).items()}
    rows = [dict(r) for r in con.execute(
        "SELECT id, fonte, nome, start_date, local_nome, endereco, organizador,"
        "       imagem, end_date, lat, preco_min FROM tratado.eventos WHERE ruido = 0")]

    por_dia = {}
    for r in rows:
        dt = tempo.instante(r["start_date"])
        if dt is None:
            continue
        r["nome_cmp"] = _nome_comparavel(r["nome"])
        local = _normalizar_texto(r["local_nome"])
        r["local_cmp"] = canon_local.get(local, local)
        por_dia.setdefault(dt.astimezone(_FUSO_BRASILIA).date(), []).append(r)

    # Union-find sobre os ids (fecho transitivo dos pares).
    pai = {}

    def achar(x):
        while pai.get(x, x) != x:
            pai[x] = pai.get(pai[x], pai[x])
            x = pai[x]
        return x

    def unir(x, y):
        pai.setdefault(x, x)
        pai.setdefault(y, y)
        rx, ry = achar(x), achar(y)
        if rx != ry:
            pai[ry] = rx

    for _, evs in sorted(por_dia.items()):
        for i, a in enumerate(evs):
            for b in evs[i + 1:]:
                # pares da MESMA fonte também entram (NI-01) — a regra
                # apertada fica dentro de _e_duplicata
                if _e_duplicata(a, b):
                    unir(a["id"], b["id"])

    membros = {}
    por_id = {r["id"]: r for r in rows}
    for ev_id in pai:
        membros.setdefault(achar(ev_id), []).append(por_id[ev_id])

    def completude(r):
        return sum(1 for c in _CAMPOS_COMPLETUDE if r.get(c))

    grupos = []
    for grupo in membros.values():
        if len(grupo) < 2:
            continue
        grupo.sort(key=lambda r: (-completude(r),
                                  _PREF_FONTE.get(r["fonte"], 9), r["id"]))
        canonico = grupo[0]
        for r in grupo:
            con.execute(
                "UPDATE tratado.eventos SET dedupe_grupo = %s, dedupe_canonico = %s "
                "WHERE id = %s",
                (canonico["id"], 1 if r["id"] == canonico["id"] else 0, r["id"]))
        grupos.append(grupo)
    return grupos


def aplicar(con, aliases_local=None):
    """Reseta e reaplica todo o enriquecimento v1. Retorna dados p/ relatório.

    aliases_local: grafias equivalentes de local p/ o dedupe (ver
    _agrupar_duplicatas); o atualizar.py passa as da watchlist do Instagram.

    Returns:
        dict com:
          ruido: lista de (nome, termo que marcou)
          grupos: lista de grupos de dedupe; cada grupo é uma lista de dicts
                  dos membros (canônico primeiro), com fonte/nome/id.
    """
    con.execute("UPDATE tratado.eventos SET ruido = 0, ruido_motivo = NULL, "
                "dedupe_grupo = NULL, dedupe_canonico = 1")
    ruido = _marcar_ruido(con)
    grupos = _agrupar_duplicatas(con, aliases_local)
    con.commit()
    return {"ruido": ruido, "grupos": grupos}
