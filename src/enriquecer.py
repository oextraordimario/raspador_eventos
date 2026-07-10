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
from difflib import SequenceMatcher

import tempo

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

# Ordem de preferência para o canônico em caso de empate de completude
# (Sympla costuma trazer mais metadados).
_PREF_FONTE = {"sympla": 0, "shotgun": 1, "ingresse": 2}

# Campos cuja presença mede a "completude" de um registro (escolha do canônico).
_CAMPOS_COMPLETUDE = ["endereco", "local_nome", "organizador", "imagem",
                      "end_date", "lat"]


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
    for r in con.execute("SELECT id, nome FROM eventos"):
        m = _RUIDO_RE.search(_normalizar_texto(r["nome"]))
        if m:
            con.execute("UPDATE eventos SET ruido = 1, ruido_motivo = ? "
                        "WHERE id = ?", (m.group(1), r["id"]))
            marcados.append((r["nome"], m.group(1)))
    return marcados


def _e_duplicata(a, b):
    sim = _sim(a["nome_cmp"], b["nome_cmp"])
    if sim >= SIM_NOME_FORTE:
        return True
    if sim >= SIM_NOME_FRACA and a["local_cmp"] and a["local_cmp"] == b["local_cmp"]:
        return True
    return False


def _agrupar_duplicatas(con):
    """Agrupa duplicatas cross-fonte (mesmo dia UTC + regras de similaridade).

    Retorna a lista de grupos, cada um como lista de dicts dos membros
    (canônico primeiro).
    """
    rows = [dict(r) for r in con.execute(
        "SELECT id, fonte, nome, start_date, local_nome, endereco, organizador,"
        "       imagem, end_date, lat FROM eventos WHERE ruido = 0")]

    por_dia = {}
    for r in rows:
        dt = tempo.instante(r["start_date"])
        if dt is None:
            continue
        r["nome_cmp"] = _nome_comparavel(r["nome"])
        r["local_cmp"] = _normalizar_texto(r["local_nome"])
        por_dia.setdefault(dt.date(), []).append(r)

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
                if a["fonte"] != b["fonte"] and _e_duplicata(a, b):
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
                "UPDATE eventos SET dedupe_grupo = ?, dedupe_canonico = ? "
                "WHERE id = ?",
                (canonico["id"], 1 if r["id"] == canonico["id"] else 0, r["id"]))
        grupos.append(grupo)
    return grupos


def aplicar(con):
    """Reseta e reaplica todo o enriquecimento v1. Retorna dados p/ relatório.

    Returns:
        dict com:
          ruido: lista de (nome, termo que marcou)
          grupos: lista de grupos de dedupe; cada grupo é uma lista de dicts
                  dos membros (canônico primeiro), com fonte/nome/id.
    """
    con.execute("UPDATE eventos SET ruido = 0, ruido_motivo = NULL, "
                "dedupe_grupo = NULL, dedupe_canonico = 1")
    ruido = _marcar_ruido(con)
    grupos = _agrupar_duplicatas(con)
    con.commit()
    return {"ruido": ruido, "grupos": grupos}
