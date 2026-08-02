"""Gerador do mapa de linhagem — de onde vem cada dado e por onde ele passou.

Uso (da raiz do repo):
    python src/ferramentas/linhagem.py          # regrava docs/linhagem/LINHAGEM.md

**POR QUE UM GERADOR, E NÃO UMA FERRAMENTA DE PRATELEIRA.** A pesquisa está em
docs/pesquisas/20260802_ferramentas-linhagem.md; o resumo é que toda ferramenta
automática (Marquez, DataHub, OpenMetadata, sqllineage) deriva linhagem de SQL
ou de hooks de orquestrador, e aqui a transformação é PYTHON: um parser de SQL
veria o `INSERT INTO tratado.eventos` do `comum.py` sem saber que ele veio de
`cru.sympla` via `tratamento/sympla.py` — justamente a pergunta a responder.
Em qualquer cenário o grafo seria escrito à mão; a escolha real era onde ele
mora, e mora aqui.

**POR QUE ELE LÊ O CÓDIGO, E NÃO UM CADASTRO.** Diagrama mantido à mão
desatualiza no primeiro commit em que ninguém lembra dele — e diagrama errado é
pior que diagrama nenhum, porque é consultado com confiança. Aqui a fonte é o
próprio código: fonte nova entra em `gravar.FONTES` + `comum.TRILHAS` para o
pipeline funcionar, e por isso aparece no mapa sem ninguém se lembrar disso.

**POR QUE VÁRIOS DIAGRAMAS, E NÃO UM SÓ.** A primeira versão desenhava o grafo
inteiro — 62 nós — e ficou ilegível. O Mermaid posiciona sozinho (não há como
arrastar caixa), então o único controle real sobre o resultado é QUANTO se pede
a ele: uma panorâmica agregada responde "como o dado anda por aqui", e um
diagrama por domínio responde "o que acontece com ESTA fonte". Cada um é uma
fatia do mesmo grafo, filtrada pelos módulos que interessam.

Nada é importado — a leitura é por AST e regex sobre os arquivos. É de
propósito: importar `tratamento.ciclo` arrastaria o grafo de import das oito
fontes para dentro de uma ferramenta que só quer desenhar, e um dia isso pediria
uma conexão com a base para gerar um documento estático.

O que ele lê, e de onde:
    coleta/gravar.py     FONTES, ERAS (qual endpoint produziu cada payload)
    tratamento/comum.py  TRILHAS (fonte -> módulo de tratamento)
    tratamento/<f>.py    DERIVACOES, LOTES, CONFERIR
    tratamento/ciclo.py  a ORDEM real dos passos a seco (AST da `executar`)
    sql/**/*.sql         os objetos de cada camada, a política do cabeçalho e as
                         dependências de cada view de `public`
    src/**/*.py          quem lê e quem escreve cada tabela qualificada
    quem importa servico/consulta.py -> as portas de consumo
"""

import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SRC = RAIZ / "src"
SAIDA = RAIZ / "docs" / "linhagem" / "LINHAGEM.md"

CAMADAS = ("cru", "tratado", "curado", "operacao", "uso", "public")

# Rótulo de cada camada nos diagramas. O texto é o contrato da camada, não
# decoração: é ele que responde "posso dropar isto?" na hora do aperto.
LEGENDA = {
    "cru": "cru — bronze: o que a fonte disse. NUNCA SE DROPA",
    "tratado": "tratado — prata: o schema unificado. Descartável por desenho",
    "curado": "curado — o que uma PESSOA decidiu. NUNCA SE DROPA",
    "operacao": "operacao — telemetria e artefatos nossos. NUNCA SE DROPA",
    "uso": "uso — quem usou (LGPD). NUNCA SE DROPA",
    "public": "public — só views: o contrato de consumo",
}

# Cor por camada. Fundos CLAROS com traço e texto escuros de propósito: o
# GitHub renderiza o mesmo Mermaid em tema claro e escuro sem avisar qual, e
# fundo claro com texto escuro é o único par que sobrevive aos dois.
PALETA = {
    "fonte": "fill:#eceef0,stroke:#8b949e,color:#24292f",
    "coleta": "fill:#dceaf7,stroke:#3f7cae,color:#12304a",
    "cru": "fill:#f6e6cd,stroke:#a8722c,color:#4a3214",
    "tratamento": "fill:#e7e2f3,stroke:#6b5ca5,color:#2e2650",
    "tratado": "fill:#e6e9ec,stroke:#6b7280,color:#2b3138",
    "curado": "fill:#dfe3f6,stroke:#4c5fa8,color:#232c5a",
    "operacao": "fill:#e6ecd8,stroke:#6b7f3a,color:#2f3a19",
    "uso": "fill:#f7e2e2,stroke:#a85c5c,color:#4a2020",
    "public": "fill:#d7ecea,stroke:#0f6e6e,color:#0a3b3b",
    "consumo": "fill:#c9e4e1,stroke:#0b5450,color:#062f2d",
    "pipeline": "fill:#e3e6e9,stroke:#5b6b7a,color:#232c33",
    "ferramentas": "fill:#f0e8dd,stroke:#8a7154,color:#3d3125",
    "servico": "fill:#cfe3e6,stroke:#3f7f88,color:#123236",
}

_RE_DEF_SQL = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([a-z_]+\.[a-z_]+)", re.I)

# A referência a uma tabela em SQL solto dentro do Python. Só nome QUALIFICADO
# por schema: `eventos.` sem schema aparece em alias e em ON CONFLICT, e chutar
# a que tabela pertence produziria aresta inventada.
_RE_REF = re.compile(
    r"\b(INSERT INTO|UPDATE|DELETE FROM|FROM|JOIN)\s+"
    r"((?:" + "|".join(CAMADAS) + r")\.[a-z_{}]+)", re.I)

_ESCRITA = {"INSERT INTO", "UPDATE", "DELETE FROM"}

# Pastas de código que falam com a base, e o rótulo do grupo no diagrama.
PASTAS = {
    "coleta": "coleta/ — só fala com a fonte",
    "tratamento": "tratamento/ — a seco, nenhuma rede",
    "pipeline": "pipeline/ — orquestração da rodada",
    "ferramentas": "ferramentas/ — fora do pipeline",
    "servico": "servico/ — as portas",
}


# --------------------------------------------------------------- leitura SQL

def _paragrafos(texto):
    """Os parágrafos de comentário do topo do arquivo — onde mora a política."""
    blocos, atual = [], []
    for linha in texto.splitlines():
        if not linha.startswith("--"):
            break
        conteudo = linha.lstrip("- ").rstrip()
        if conteudo:
            atual.append(conteudo)
        elif atual:
            blocos.append(" ".join(atual))
            atual = []
    if atual:
        blocos.append(" ".join(atual))
    return blocos


_RE_POLITICA = re.compile(r"^POL[IÍ]TICA[^:]*:\s*(.+)$", re.I)
_RE_HERANCA = re.compile(
    r"(?:mesma pol[ií]tica d[oe]|cabe[cç]alho de)\s+([\w/]+\.sql)", re.I)


def _politica(texto):
    """(frase declarada, herda_de) — o que o .sql AFIRMA sobre a própria tabela.

    Lê a declaração em vez de repetir a regra aqui: se a política de uma tabela
    mudar, ela muda no arquivo dela e o mapa acompanha.

    A frase sai INTEIRA, e não reduzida a etiquetas do tipo "append-only". A
    tentação de etiquetar é grande e foi tentada: acontece que o cabeçalho é
    PROSA, e prosa afirma e nega no mesmo parágrafo — `cru.tmdb` diz "Nao e
    append-only" e saía rotulada `append-only`, `cru.inventario` saía
    `append-only` por descrever as tabelas que a view lê. Etiqueta errada num
    mapa de linhagem é pior que etiqueta nenhuma, porque é lida com confiança e
    a pergunta que ela responde é "posso dropar isto?".

    A busca é no parágrafo que COMEÇA com "POLITICA" — o resto do cabeçalho é
    explicação, não declaração.
    """
    blocos = _paragrafos(texto)
    for bloco in blocos:
        m = _RE_POLITICA.match(bloco)
        if m:
            return re.sub(r"\*\*", "", m.group(1)), None
    for bloco in blocos:
        m = _RE_HERANCA.search(bloco)
        if m:
            return None, m.group(1)
    return "", None


def _objetos_sql():
    """{"cru.sympla": {tipo, arquivo, politica, deps}} — deps só para views.

    O corpo de cada definição é fatiado do CREATE dela até o próximo, para a
    view levar as dependências DELA e não as do arquivo inteiro (`zz_views.sql`
    define cinco).
    """
    arquivos, objetos = {}, {}
    for caminho in sorted((RAIZ / "sql").rglob("*.sql")):
        if caminho.parent.name == "manutencao":
            continue
        texto = caminho.read_text(encoding="utf-8")
        rel = caminho.relative_to(RAIZ / "sql").as_posix()
        arquivos[rel] = _politica(texto)
        achados = list(_RE_DEF_SQL.finditer(texto))
        for i, m in enumerate(achados):
            fim = achados[i + 1].start() if i + 1 < len(achados) else len(texto)
            corpo = texto[m.end():fim]
            deps = sorted({d for _, d in _RE_REF.findall(corpo)})
            objetos[m.group(2)] = {
                "tipo": m.group(1).lower(),
                "arquivo": caminho.relative_to(RAIZ).as_posix(),
                "sql": rel,
                "deps": [d for d in deps if d != m.group(2)],
            }

    # Segunda passada: os arquivos que remetem a outro em vez de repetir o texto
    # ("mesma politica do cru/sympla.sql", nas quatro bronzes de plataforma).
    # Herdar é o que o arquivo MANDA fazer; a alternativa era deixá-los sem
    # política no mapa, o que leria como "esta aqui pode ser dropada".
    for obj in objetos.values():
        frase, herda = arquivos[obj["sql"]]
        if herda:
            pasta = obj["sql"].rsplit("/", 1)[0]
            alvo = herda if herda in arquivos else f"{pasta}/{herda}"
            if alvo in arquivos and arquivos[alvo][0]:
                frase = f"{arquivos[alvo][0]} — declarada em `sql/{alvo}`"
        obj["politica"] = frase or ""
    return objetos


# ------------------------------------------------------------ leitura Python

def _modulos(pasta):
    """{"sympla": (caminho, primeira frase da docstring)} de uma pasta de src/."""
    achados = {}
    for caminho in sorted((SRC / pasta).glob("*.py")):
        if caminho.stem == "__init__":
            continue
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        doc = (ast.get_docstring(arvore) or "").strip()
        resumo = re.split(r"(?<=\.)\s", doc.replace("\n", " "), maxsplit=1)[0]
        achados[caminho.stem] = (caminho, resumo)
    return achados


def _refs(caminho):
    """(lidas, escritas) — as tabelas que o módulo toca, pelo SQL que ele monta.

    `cru.{fonte}` (f-string) vira `cru.<fonte>`, e a view `_atual` é creditada à
    tabela que ela espelha: o tratamento lê pela view, mas a procedência do dado
    é a tabela.
    """
    texto = caminho.read_text(encoding="utf-8")
    # SQL que o módulo carrega de arquivo em vez de montar em string: sem isto,
    # `tratamento/busca.py` — que roda `manutencao/reconstruir_fts.sql` — sairia
    # como um passo do ciclo que não toca em tabela nenhuma.
    for m in re.finditer(r'ler_sql\(\s*"([\w/.\-]+\.sql)"', texto):
        alvo = RAIZ / "sql" / m.group(1)
        if alvo.exists():
            texto += "\n" + alvo.read_text(encoding="utf-8")

    lidas, escritas = set(), set()
    for verbo, tabela in _RE_REF.findall(texto):
        tabela = tabela.replace("{fonte}", "<fonte>")
        tabela = re.sub(r"_atual$", "", tabela)
        (escritas if verbo.upper() in _ESCRITA else lidas).add(tabela)
    return sorted(lidas - escritas), sorted(escritas)


def _atribuicoes(caminho):
    """{nome: nó} das atribuições de nível de módulo — para ler as constantes."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    achados = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    achados[alvo.id] = no.value
    return achados


def _chaves(no):
    """As chaves de um dict literal cujos VALORES não são literais.

    `TRILHAS` mapeia para módulos e `DERIVACOES` para funções: `literal_eval`
    engasgaria nos dois, e o que interessa aqui é a chave.
    """
    if not isinstance(no, ast.Dict):
        return []
    return [k.value for k in no.keys if isinstance(k, ast.Constant)]


def _statements(corpo):
    """Os statements de um corpo, entrando em `if`/`for`/`with`."""
    for no in corpo:
        yield no
        for campo in ("body", "orelse", "finalbody"):
            yield from _statements(getattr(no, campo, None) or [])


def _ordem_ciclo(modulos_tratamento):
    """A ordem dos passos a seco, lida da `ciclo.executar`.

    Sai do AST e não de uma lista aqui porque a ordem É a regra — o cabeçalho do
    `ciclo.py` documenta cinco pontos em que ela importa. Uma cópia manual
    divergiria no dia em que um passo mudasse de lugar, que é exatamente o dia em
    que alguém consultaria o mapa.

    Passo é chamada em posição de STATEMENT (`x.aplicar(con)` solto ou atribuído),
    não qualquer chamada dentro da função: `curadoria.locais_canonicos(con)` mora
    aninhada num dict de aliases, é insumo do passo seguinte e não um passo — e
    entrava na lista rotulada com o que o MÓDULO `curadoria` escreve, que ela não
    escreve.
    """
    arvore = ast.parse((SRC / "tratamento" / "ciclo.py").read_text(encoding="utf-8"))
    executar = next(n for n in ast.walk(arvore)
                    if isinstance(n, ast.FunctionDef) and n.name == "executar")
    passos, vistos = [], set()
    for no in sorted(_statements(executar.body), key=lambda n: n.lineno):
        chamada = getattr(no, "value", None)
        if not isinstance(no, (ast.Expr, ast.Assign)) or not isinstance(chamada, ast.Call):
            continue
        f = chamada.func
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id in modulos_tratamento):
            passo = f"{f.value.id}.{f.attr}"
            if passo not in vistos:
                vistos.add(passo)
                passos.append((f.value.id, f.attr))
    return passos


def _consumidores():
    """Os arquivos que importam a camada de consulta — as portas de saída.

    `tests/` fica de fora: teste consome tudo por definição e não é porta.
    """
    achados = []
    for caminho in sorted(RAIZ.rglob("*.py")):
        rel = caminho.relative_to(RAIZ).as_posix()
        if rel.startswith(("tests/", "src/ferramentas/")) or "site-packages" in rel:
            continue
        if re.search(r"^from servico import .*\bconsulta\b",
                     caminho.read_text(encoding="utf-8"), re.M):
            achados.append(rel)
    return achados


# --------------------------------------------------------------------- grafo

def _expandir(tabelas, fontes, objetos):
    """`cru.<fonte>` vira as cinco tabelas de plataforma; o resto passa direto.

    Tabela que não existe no DDL é descartada: se o SQL de um módulo cita algo
    que `sql/` não define, o mapa não inventa o nó — o erro está no código, e
    inventar o nó o esconderia.
    """
    saida = []
    for tabela in tabelas:
        if "<fonte>" in tabela:
            saida.extend(tabela.replace("<fonte>", f) for f in fontes)
        else:
            saida.append(tabela)
    return [t for t in saida if t in objetos]


def _grafo(dados):
    """O grafo INTEIRO, uma vez: {id: (rotulo, classe)} e a lista de arestas.

    Cada diagrama do documento é uma fatia disto. Montar o grafo uma vez e
    filtrar é o que impede as versões de divergirem — antes de existir esta
    função, o mapa e os recortes teriam duas regras de aresta para manter
    iguais, e o dia em que discordassem ninguém notaria.
    """
    objetos, fontes, trilhas = dados["objetos"], dados["fontes"], dados["trilhas"]
    nos, arestas = {}, []

    def no(ident, rotulo, classe):
        nos[ident] = (rotulo, classe)
        return ident

    def liga(a, b):
        if (a, b) not in arestas:
            arestas.append((a, b))

    tabelas_cru = [n for n, o in objetos.items()
                   if n.startswith("cru.") and o["tipo"] == "table"]

    for nome, obj in objetos.items():
        if nome.endswith("_atual"):
            continue
        camada = nome.split(".", 1)[0]
        detalhe = _curto(obj["politica"]) or (
            "view" if obj["tipo"] == "view" else "")
        no(nome, nome + (f"<br/>{detalhe}" if detalhe else ""), camada)

    # Fonte externa -> módulo de coleta -> gravar -> bronze. `gravar.py` é um nó
    # só porque é isso que ele é no código: a única escrita em `cru`.
    no("col.gravar", "coleta/gravar.py<br/>a única escrita em cru", "coleta")
    for tabela in tabelas_cru:
        fonte = tabela.split(".", 1)[1]
        endpoints = sorted({v for (f, _), v in dados["eras"].items() if f == fonte})
        no(f"ext.{fonte}", fonte + ("<br/>" + " · ".join(endpoints) if endpoints else ""),
           "fonte")
        entrada = "col.gravar"
        if fonte in dados["coleta"]:
            entrada = no(f"col.{fonte}", f"coleta/{fonte}.py", "coleta")
            liga(entrada, "col.gravar")
        liga(f"ext.{fonte}", entrada)
        liga("col.gravar", tabela)

    for pasta in PASTAS:
        for mod, (caminho, _) in dados[pasta].items():
            lidas, escritas = _refs(caminho)
            if not (lidas or escritas) or (pasta, mod) == ("coleta", "gravar"):
                continue
            ident = no(f"{pasta}.{mod}", f"{pasta}/{mod}.py",
                       "tratamento" if pasta == "tratamento" else pasta)
            for tabela in _expandir(lidas, fontes, objetos):
                liga(tabela, ident)
            for tabela in _expandir(escritas, fontes, objetos):
                liga(ident, tabela)

    # A trilha por fonte é declarativa (TRILHAS), não sai do SQL: o módulo da
    # fonte não sabe SQL — quem escreve é o motor.
    for fonte in trilhas:
        ident = no(f"tratamento.{fonte}", f"tratamento/{fonte}.py<br/>trilha da fonte",
                   "tratamento")
        liga(f"cru.{fonte}", ident)
        liga(ident, "tratamento.comum")

    no("srv.consulta", "servico/consulta.py<br/>camada canônica", "consumo")
    for nome, obj in objetos.items():
        if nome.startswith("public."):
            for dep in obj["deps"]:
                if dep in nos:
                    liga(dep, nome)
            liga(nome, "srv.consulta")
    for porta in dados["consumidores"]:
        liga("srv.consulta", no(porta, porta, "consumo"))

    return nos, arestas


# ------------------------------------------------------------------ diagrama

def _id(nome):
    return re.sub(r"\W", "_", nome)


def _curto(txt, n=44):
    """A declaração inteira não cabe num nó: fica a primeira frase, truncada.

    Cortar é honesto; resumir seria reescrever a política com outras palavras,
    que é como um mapa gerado começa a divergir do que ele mapeia. A declaração
    completa está na tabela de inventário, no fim do documento.
    """
    txt = re.split(r"(?<=\.)\s", " ".join(txt.split()), maxsplit=1)[0]
    return txt if len(txt) <= n else txt[:n].rstrip(" ,;—-") + "…"


def _rotulo(txt):
    # Aspas duplas fecham o label no Mermaid e quebram o diagrama inteiro — e
    # elas aparecem nos cabeçalhos ("muda de dono", em operacao/slugs.sql).
    return txt.replace('"', "'")


# Título do grupo de cada classe de nó no diagrama.
GRUPOS = dict(LEGENDA, fonte="fontes externas", consumo="portas de consumo",
              **{p: t for p, t in PASTAS.items() if p != "tratamento"},
              tratamento=PASTAS["tratamento"])

ORDEM_GRUPO = ("fonte", "coleta", "cru", "tratamento", "tratado", "curado",
               "operacao", "uso", "public", "pipeline", "ferramentas",
               "servico", "consumo")


def _mermaid(grafo, escolhidos, direcao="LR"):
    """Renderiza UMA fatia do grafo, agrupada por classe e colorida por camada."""
    nos, arestas = grafo
    escolhidos = [i for i in escolhidos if i in nos]
    L = [f"flowchart {direcao}"]
    for grupo in ORDEM_GRUPO:
        do_grupo = [i for i in escolhidos if nos[i][1] == grupo]
        if not do_grupo:
            continue
        L.append(f'  subgraph g_{grupo}["{GRUPOS[grupo]}"]')
        L.append("    direction TB")
        for ident in do_grupo:
            L.append(f'    {_id(ident)}["{_rotulo(nos[ident][0])}"]')
        L.append("  end")

    dentro = set(escolhidos)
    for a, b in arestas:
        if a in dentro and b in dentro:
            L.append(f"  {_id(a)} --> {_id(b)}")

    for grupo in ORDEM_GRUPO:
        do_grupo = [_id(i) for i in escolhidos if nos[i][1] == grupo]
        if do_grupo:
            L.append(f"  classDef {grupo} {PALETA[grupo]}")
            L.append(f"  class {','.join(do_grupo)} {grupo}")
    return "```mermaid\n" + "\n".join(L) + "\n```"


def _vizinhanca(grafo, sementes, saltos=1):
    """Os nós das sementes mais o que está a `saltos` de distância delas.

    É assim que um recorte por domínio se monta sem lista manual: as sementes
    são os MÓDULOS do domínio, e a vizinhança traz as tabelas que eles tocam.
    """
    nos, arestas = grafo
    atual = {s for s in sementes if s in nos}
    for _ in range(saltos):
        vizinhos = {b for a, b in arestas if a in atual}
        vizinhos |= {a for a, b in arestas if b in atual}
        atual |= vizinhos
    return [i for i in nos if i in atual]


def _diagrama_ciclo(dados):
    """O segundo tempo da rodada: a ordem dos passos a seco, numa transação só."""
    L = ["flowchart TD"]
    anterior = None
    for i, (mod, funcao) in enumerate(dados["ordem_ciclo"]):
        _, escritas = _refs(dados["tratamento"][mod][0])
        detalhe = ""
        if escritas:
            detalhe = "<br/>escreve: " + ", ".join(
                sorted({t.split(".", 1)[1] for t in escritas}))
        L.append(f'  p{i}["{i + 1}. {mod}.{funcao}(){detalhe}"]')
        if anterior is not None:
            L.append(f"  p{anterior} --> p{i}")
        anterior = i
    L.append('  commit["um commit — o site e o MCP só veem o depois"]')
    L.append(f"  p{anterior} --> commit")
    L.append(f"  classDef passo {PALETA['tratamento']}")
    L.append(f"  class {','.join(f'p{i}' for i in range(len(dados['ordem_ciclo'])))} passo")
    L.append(f"  classDef fim {PALETA['public']}")
    L.append("  class commit fim")
    return "```mermaid\n" + "\n".join(L) + "\n```"


def _diagrama_panoramica(dados, grafo):
    """A vista de cima: as camadas e o volume de cada uma, sem um nó por tabela.

    Agregada de propósito — é a resposta para "como o dado anda por aqui", e
    nenhuma pergunta dessas se responde melhor com 62 caixas na tela.
    """
    objetos = dados["objetos"]
    conta = {c: len([n for n in objetos if n.startswith(c + ".")
                     and not n.endswith("_atual")]) for c in CAMADAS}
    plataformas = len(dados["trilhas"])
    proprias = len([n for n, o in objetos.items()
                    if n.startswith("cru.") and o["tipo"] == "table"]) - plataformas
    passos = len(dados["ordem_ciclo"])
    portas = len(dados["consumidores"])
    L = [
        "flowchart LR",
        f'  f1["{plataformas} plataformas de ingresso<br/>Sympla · Ingresse · Zig · Shotgun · Ticket and Go"]',
        f'  f2["{proprias} fontes de contrato próprio<br/>cinema · Instagram · TMDB"]',
        '  c["coleta/<br/>tudo que tem rede"]',
        f'  b["cru — {conta["cru"]} tabelas<br/>o payload como a fonte mandou"]',
        f'  t["tratamento/<br/>a seco, {passos} passos numa transação"]',
        f'  p["tratado — {conta["tratado"]} tabelas<br/>o schema unificado"]',
        f'  h["curado — {conta["curado"]}<br/>decisão humana"]',
        f'  o["operacao — {conta["operacao"]}<br/>telemetria"]',
        f'  v["public — {conta["public"]} views<br/>o contrato de consumo"]',
        f'  s["{portas} portas<br/>site · MCP"]',
        "  f1 --> c", "  f2 --> c", "  c --> b", "  b --> t", "  t --> p",
        "  h --> t", "  o --> t", "  t --> o", "  p --> v", "  v --> s",
        f"  classDef fonte {PALETA['fonte']}",
        f"  classDef coleta {PALETA['coleta']}",
        f"  classDef cru {PALETA['cru']}",
        f"  classDef tratamento {PALETA['tratamento']}",
        f"  classDef tratado {PALETA['tratado']}",
        f"  classDef curado {PALETA['curado']}",
        f"  classDef operacao {PALETA['operacao']}",
        f"  classDef public {PALETA['public']}",
        f"  classDef consumo {PALETA['consumo']}",
        "  class f1,f2 fonte", "  class c coleta", "  class b cru",
        "  class t tratamento", "  class p tratado", "  class h curado",
        "  class o operacao", "  class v public", "  class s consumo",
    ]
    return "```mermaid\n" + "\n".join(L) + "\n```"


# ------------------------------------------------------------------ markdown

def _tabela(cabecalho, linhas):
    sep = "|".join("---" for _ in cabecalho)
    corpo = "\n".join("| " + " | ".join(c) + " |" for c in linhas)
    return f"| {' | '.join(cabecalho)} |\n|{sep}|\n{corpo}"


def _markdown(dados):
    objetos, tratamento = dados["objetos"], dados["tratamento"]
    grafo = _grafo(dados)
    trilhas = dados["trilhas"]

    partes = [
        "# Linhagem — a trajetória do dado",
        "",
        "> **Arquivo gerado. Não edite à mão.** Regrave com",
        "> `python src/ferramentas/linhagem.py` — ele lê o próprio código, então",
        "> fonte nova aparece aqui sozinha. O porquê de ser um gerador e não uma",
        "> ferramenta de prateleira está em",
        "> `docs/pesquisas/20260802_ferramentas-linhagem.md`.",
        "",
        "Os diagramas são cortes do MESMO grafo, do mais geral para o mais",
        "detalhado. A cor é a camada; o cinza-azulado à esquerda é sempre o que",
        "está fora daqui.",
        "",
        "> Para apresentar, tem o [`linhagem.excalidraw`](linhagem.excalidraw) aqui",
        "> do lado ([prévia](linhagem.png)): as mesmas camadas desenhadas à mão,",
        "> com as caixas arrastáveis. **Ele é um snapshot — não se regenera com",
        "> este arquivo e não acompanha mudança no pipeline.** Em qualquer",
        "> divergência, quem vale é este documento.",
        "",
        "## 1. Panorâmica",
        "",
        "A regra que o desenho inteiro serve: **tudo que tem rede é coleta e",
        "escreve só em `cru`/`operacao`; tudo que é a seco é tratamento, e ele é o",
        "único que escreve em `tratado`.**",
        "",
        _diagrama_panoramica(dados, grafo),
        "",
        "## 2. As plataformas de ingresso",
        "",
        "Uma trilha por fonte, e todas desembocam no mesmo motor: o",
        "`tratamento/comum.py` faz o upsert em `tratado.eventos` e agrega os lotes.",
        "O módulo da fonte não sabe SQL — ele só declara como ler o payload dela.",
        "",
        _mermaid(grafo, _vizinhanca(grafo, [f"tratamento.{f}" for f in trilhas]
                                   + [f"col.{f}" for f in trilhas]
                                   + ["col.gravar", "tratamento.comum"])),
        "",
    ]

    # Os domínios de contrato próprio: módulos de tratamento fora das TRILHAS
    # que escrevem na prata. Sai da estrutura, não de uma lista aqui — um
    # domínio novo (um `tratamento/teatro.py`) ganha sua seção sozinho.
    proprios = [m for m, (c, _) in tratamento.items()
                if m not in trilhas and m not in ("comum", "ciclo", "bairros")
                and any(t.startswith("tratado.") for t in _refs(c)[1])
                and any(t.startswith("cru.") for t in _refs(c)[0])]
    for i, mod in enumerate(proprios, start=3):
        # As sementes incluem a COLETA de cada bronze que o módulo lê — assim o
        # recorte começa na fonte externa e não na tabela já gravada. Sai do
        # grafo (quais `cru.*` o módulo lê), não de um palpite pelo nome: o
        # domínio do cinema lê `cru.tmdb`, que não se parece com "cinema".
        origens = [t.split(".", 1)[1] for t in _refs(tratamento[mod][0])[0]
                   if t.startswith("cru.")]
        sementes = [f"tratamento.{mod}"] + [f"col.{o}" for o in origens]
        partes += [
            f"## {i}. {mod.capitalize()}",
            "",
            tratamento[mod][1],
            "",
            _mermaid(grafo, _vizinhanca(grafo, sementes)),
            "",
        ]

    n = 3 + len(proprios)
    resto = [f"tratamento.{m}" for m in tratamento
             if m not in trilhas and m not in proprios
             and m not in ("comum", "ciclo", "bairros")]
    partes += [
        f"## {n}. Curadoria, telemetria e endereços",
        "",
        "O que não vem de fonte nenhuma: a decisão humana (`curado`), o que a",
        "própria rodada registrou sobre si (`operacao`) e o endereço público de",
        "cada registro. É daqui que sai o `sumido` — evento que não reapareceu no",
        "catálogo —, e é por isso que ele depende de `operacao.coletas` ter",
        "registrado uma coleta boa.",
        "",
        _mermaid(grafo, _vizinhanca(
            grafo, resto + [f"pipeline.{m}" for m in dados["pipeline"]]
            + [f"ferramentas.{m}" for m in dados["ferramentas"]])),
        "",
        f"## {n + 1}. O ciclo do tratamento",
        "",
        "O segundo tempo de toda rodada (`tratamento/ciclo.py`), na ordem lida do",
        "código. Roda numa transação só: enquanto reconstrói `tratado`, o site e o",
        "MCP seguem lendo a versão anterior por `public`.",
        "",
        _diagrama_ciclo(dados),
        "",
        f"## {n + 2}. Trilha por fonte",
        "",
        "As colunas de origem dizem qual endpoint produziu cada payload",
        "(`gravar.ERAS`) e o que cada um alimenta.",
        "",
    ]

    linhas = []
    for fonte in dados["fontes"]:
        origens = sorted({o for f, o in dados["eras"] if f == fonte})
        eras = ", ".join(f"`{o}`: {dados['eras'][(fonte, o)]}" for o in origens)
        deriv = ", ".join(dados["derivacoes"].get(fonte, ())) or "—"
        lotes = ", ".join(dados["lotes"].get(fonte, ())) or "—"
        linhas.append([f"**{fonte}**", eras or "—", f"`cru.{fonte}`",
                       f"`tratamento/{fonte}.py`", deriv, lotes])
    partes += [_tabela(["fonte", "endpoints por origem", "bronze", "trilha",
                        "derivações", "lotes"], linhas), ""]

    partes += [
        f"## {n + 3}. Inventário por camada",
        "",
        "Cada objeto do DDL, a política declarada no cabeçalho do `.sql` dele e",
        "quem o toca no código. É esta tabela que responde \"posso dropar isto?\".",
        "",
        "Duas leituras do quadro: um módulo que **escreve** numa tabela quase",
        "sempre também a lê, e a coluna \"lido por\" só lista quem lê SEM escrever;",
        "e as views `cru.<fonte>_atual` — o estado corrente de cada bronze",
        "append-only, por onde o tratamento lê — ficam fora, com as leituras",
        "creditadas à tabela que elas espelham.",
        "",
    ]
    escritores, leitores = dados["escritores"], dados["leitores"]
    for camada in CAMADAS:
        objs = {nome: o for nome, o in objetos.items()
                if nome.startswith(camada + ".") and not nome.endswith("_atual")}
        if not objs:
            continue
        partes += [f"### `{camada}` — {LEGENDA[camada].split('—', 1)[1].strip()}",
                   ""]
        linhas = []
        for nome, obj in objs.items():
            arquivo = obj["arquivo"]
            linhas.append([
                f"`{nome}`",
                obj["tipo"],
                _curto(obj["politica"], 150) or "—",
                # ../../ e não ../: o documento mora em docs/linhagem/, dois
                # níveis abaixo da raiz, e link relativo errado é 404 silencioso
                # no GitHub — ninguém reclama, só não clica.
                f"[{arquivo}](../../{arquivo})",
                ", ".join(f"`{m}`" for m in escritores.get(nome, ())) or "—",
                ", ".join(f"`{m}`" for m in leitores.get(nome, ())) or "—",
            ])
        partes += [_tabela(["objeto", "tipo", "política declarada", "DDL",
                            "escrito por", "lido por"], linhas), ""]

    partes += [
        f"## {n + 4}. Portas de consumo",
        "",
        "Quem lê `public` pela camada canônica (`servico/consulta.py`):",
        "",
    ] + [f"- `{p}`" for p in dados["consumidores"]] + [""]
    return "\n".join(partes)


# --------------------------------------------------------------------- coleta

def _coletar():
    gravar = _atribuicoes(SRC / "coleta" / "gravar.py")
    comum = _atribuicoes(SRC / "tratamento" / "comum.py")
    fontes = list(ast.literal_eval(gravar["FONTES"]))
    trilhas = _chaves(comum["TRILHAS"])

    derivacoes, lotes = {}, {}
    for fonte in trilhas:
        consts = _atribuicoes(SRC / "tratamento" / f"{fonte}.py")
        derivacoes[fonte] = _chaves(consts.get("DERIVACOES"))
        lotes[fonte] = _chaves(consts.get("LOTES"))

    objetos = _objetos_sql()
    dados = {
        "fontes": fontes,
        "eras": ast.literal_eval(gravar["ERAS"]),
        "trilhas": trilhas,
        "derivacoes": derivacoes,
        "lotes": lotes,
        "objetos": objetos,
        "consumidores": _consumidores(),
    }
    for pasta in PASTAS:
        dados[pasta] = _modulos(pasta)
    dados["ordem_ciclo"] = _ordem_ciclo(dados["tratamento"])

    # Quem toca cada tabela, em TODO módulo que fala com a base — inclusive os
    # de fora do pipeline (`ferramentas/curar.py` é quem alimenta `curado`, e
    # deixá-lo de fora faria a camada parecer sem escritor nenhum).
    escritores, leitores = {}, {}
    for pasta in PASTAS:
        for mod, (caminho, _) in dados[pasta].items():
            lidas, escritas = _refs(caminho)
            for tabela in _expandir(escritas, fontes, objetos):
                escritores.setdefault(tabela, []).append(f"{pasta}/{mod}.py")
            for tabela in _expandir(lidas, fontes, objetos):
                leitores.setdefault(tabela, []).append(f"{pasta}/{mod}.py")
    dados["escritores"], dados["leitores"] = escritores, leitores
    return dados


def main():
    dados = _coletar()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(_markdown(dados), encoding="utf-8")
    nos, arestas = _grafo(dados)
    print(f"{SAIDA.relative_to(RAIZ).as_posix()} regravado: "
          f"{len(dados['objetos'])} objetos, {len(dados['fontes'])} plataformas, "
          f"{len(dados['ordem_ciclo'])} passos no ciclo, "
          f"grafo com {len(nos)} nós e {len(arestas)} arestas.")


if __name__ == "__main__":
    sys.exit(main())
