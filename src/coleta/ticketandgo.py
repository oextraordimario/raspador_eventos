"""Raspador do Ticket and Go (ticketandgo.com.br) via API interna do site.

Descoberta original (spike spikes/zig-ticketandgo/, 2026-07-12): o site é um
SPA Vue/Vite atrás de queue-it e a API de leitura é aberta. Em **2026-07-28 a
API V1 que usávamos foi DESLIGADA** (404 em `POST /eventos/pesquisa` e em
`GET /eventos/{slug}`, com o host de pé). O bundle do site mostrou para onde o
front foi — e é o que este módulo usa agora:

  GET  {V2}/api/v2/site/list/all?filter=&page=N&perPage=100
       -> listagem paginada do catálogo nacional (~3.600 eventos, ~430
          futuros). Payload MAGRO: uuid, slug, nome, categoria, inicio, fim,
          local, imagem. Sem hora, sem descrição, sem endereço, sem id numérico.
  GET  {V1}/eventos/{slug}/evento
       -> o detalhe (rota antiga + sufixo `/evento`), com id NUMÉRICO, hora,
          descrição HTML, `setores[].bilhetes[]` e `taxa_conveniencia`. É o
          payload do catálogo E o do passo "precificar" — os dois iguais.

O id numérico sobreviveu à migração, então a chave `ticketandgo:<id>` continua
valendo: evento que já estava na base é atualizado, não duplicado.

Particularidades da fonte:
- **Não há mais endereço.** `endereco` vem sempre vazio, cidade/estado/lat/lon
  nulos, e o site público também parou de exibir (verificado no HTML
  renderizado). O filtro DF, que era textual sobre `endereco_completo`, passou
  a se apoiar em três sinais — ver `_do_df` e `dados/locais_df.yaml`.
- Sem filtro geográfico server-side: `filter=` da V2 casa só nome/produtora
  (medido: `filter=brasilia` acha 1 dos 79 eventos DF conhecidos) e
  `uf=/estado=/cidade=` são ignorados. Por isso varremos o catálogo inteiro e
  filtramos do lado de cá — como o Zig.
- datas separadas e SEM fuso: inicio/fim "YYYY-MM-DD" + hora_incio/hora_fim
  "HH:MM:SS" (typo da fonte, sem o segundo "i") em hora local de Brasília —
  _quando compõe "YYYY-MM-DDTHH:MM:SS-03:00"; o upsert normaliza para UTC.
- cidade/estado são ROTULADOS pelo filtro (como no Shotgun), não vêm do dado.

Spec: docs/specs/20260728_fontes-quebradas/spec.md.
"""

import html
import re
import time
import json
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

API_V1 = "https://production-api-v1-service.ticketandgo.com.br"
API_V2 = "https://production-api-v2-service.ticketandgo.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# As casas de Brasília curadas à mão vivem em `curado.locais` desde 2026-07-28
# (eram dados/locais_df.yaml). Quem lê a base é o pipeline, que passa a lista
# pronta para raspar(locais_df=...) — este módulo não conhece o banco.

# Brasília é UTC-3 o ano inteiro (o DF não tem horário de verão desde 2019).
FUSO_BRASILIA = "-03:00"

# CEPs do DF começam em 70–73 (Brasília e cidades-satélites).
_CEP_DF = re.compile(r"\b7[0-3]\d{3}-?\d{3}\b")
_UF_DF = re.compile(r"\bdf\b")

# Termos geográficos INEQUÍVOCOS do DF. Ficaram de fora, de propósito, os
# ambíguos com outras cidades do país — Cruzeiro, Gama, Guará, Santa Maria,
# Varjão, Estrutural, Jardim Botânico, Sudoeste: o filtro erra para o lado de
# PERDER evento, nunca de poluir a base com outra cidade.
_TERMOS_DF = [
    "brasilia", "distrito federal", "taguatinga", "ceilandia", "samambaia",
    "planaltina", "sobradinho", "brazlandia", "candangolandia", "paranoa",
    "itapoa", "recanto das emas", "riacho fundo", "nucleo bandeirante",
    "vicente pires", "aguas claras", "asa norte", "asa sul", "plano piloto",
    "lago sul", "lago norte", "park way", "arniqueira", "octogonal",
    "eixo monumental", "esplanada dos ministerios", "setor de clubes",
    "granja do torto", "torre de tv", "ceub", "unb",
    "scen", "shis", "sqn", "sqs", "sgan", "sia", "sig", "scs", "scn", "sbn",
    "w3 norte", "w3 sul",
]
_RE_TERMOS_DF = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _TERMOS_DF) + r")\b")


def _requisitar(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json",
                      "Content-Type": "application/json",
                      "Referer": "https://www.ticketandgo.com.br/"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _limpar_html(texto):
    """HTML -> texto puro (tags viram espaco, entidades resolvidas, espacos colapsados)."""
    if not texto:
        return None
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    return re.sub(r"\s+", " ", texto).strip() or None


def _norm(texto):
    """Casefold + sem acento + espaços colapsados — para comparar nome de local."""
    texto = unicodedata.normalize("NFD", (texto or "").casefold())
    sem_acento = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento).strip()


def _do_df(local, nome=None, descricao=None, conhecidos=frozenset()):
    """O evento é de Brasília? Três sinais, do mais forte para o mais fraco.

    A fonte parou de expor endereço (NI-57), então não há campo geográfico
    para comparar — sobra texto. Medido contra os 79 eventos que estavam na
    base raspados enquanto o endereço existia: 77/77 dos que continuam no
    catálogo, sem falso positivo.

    1. `local` está em `conhecidos` (a referência canônica `curado.locais`,
       passada JÁ NORMALIZADA por quem chama — a coleta não conhece a base) —
       comparação por nome normalizado EXATO, não substring: "Comunidade das
       Nações - SIA" é do DF, "Comunidade das Nações São Paulo" não.
    2. termo geográfico inequívoco (ou CEP 70-73, ou "DF") no local/nome.
    3. CEP 70-73 ou "DF" na DESCRIÇÃO — sozinho cobre ~75% dos casos, porque a
       descrição costuma repetir o endereço completo do evento.

    "Brasília" solto na descrição NÃO conta (sinal 3 é só CEP/UF): pegava
    evento de Uberlândia cujo endereço era "Jardim Brasília, Uberlândia - MG".
    """
    if _norm(local) in conhecidos:
        return True
    campo = f"{_norm(local)} {_norm(nome)}"
    if _CEP_DF.search(campo) or _UF_DF.search(campo) or _RE_TERMOS_DF.search(campo):
        return True
    # limpa o HTML antes: "\bdf\b" casaria dentro de href/atributo de tag
    desc = _norm(_limpar_html(descricao))
    return bool(_CEP_DF.search(desc) or _UF_DF.search(desc))


def _quando(data, hora):
    """Compõe data + hora locais da fonte em ISO com o fuso de Brasília.

    Aceita data já com hora embutida ("2026-08-29 19:00:00") por robustez;
    sem hora, assume 00:00 (a data já serve ao filtro por dia).
    """
    if not data:
        return None
    data = data.strip()
    base = data.replace(" ", "T") if (" " in data or "T" in data) \
        else f"{data}T{(hora or '00:00:00').strip()}"
    return f"{base}{FUSO_BRASILIA}"


def raspar_tickets(slug):
    """Busca o detalhe do evento (setores/bilhetes + taxa_conveniencia) pelo
    slug da URL publica. Retorna {"payload": data do detalhe} para a camada
    Bronze; quem transforma em lotes/preco_min é o derivar. Levanta excecao
    em erro de rede/HTTP."""
    return {"payload": _detalhe(slug)}


def _detalhe(slug):
    """Payload rico de UM evento (rota nova: /eventos/{slug}/evento)."""
    resp = _requisitar(f"{API_V1}/eventos/{urllib.parse.quote(slug)}/evento")
    return resp.get("data") or {}


def _catalogo(max_paginas=45, por_pagina=100):
    """Percorre a listagem V2 inteira. Devolve dict slug -> item do catálogo.

    A paginação segue o `pagination.total` que a própria resposta traz (não o
    perPage pedido, que o servidor pode não respeitar). max_paginas é teto de
    segurança bem acima do catálogo conhecido (~37 páginas)."""
    itens = {}
    for pagina in range(1, max_paginas + 1):
        resp = _requisitar(
            f"{API_V2}/api/v2/site/list/all?"
            + urllib.parse.urlencode({"filter": "", "page": pagina,
                                      "perPage": por_pagina}))
        lote = resp.get("lista_evento_geral") or []
        total = (resp.get("pagination") or {}).get("total") or 0
        for ev in lote:
            if ev.get("slug"):
                itens.setdefault(ev["slug"], ev)
        print(f"  pagina {pagina}: +{len(lote)} brutos | total no site: "
              f"{total} | acumulado: {len(itens)}")
        if not lote or len(itens) >= total:
            break
    return itens


def _normalizar(det, slug, cidade_label, estado_label):
    """Detalhe da fonte -> schema unificado. `endereco`/`lat`/`lon` ficam
    NULOS de propósito: a API parou de expor endereço (não é bug a consertar,
    ver docstring do módulo). O `local` continua vindo e é o que alimenta FTS,
    dedupe e front."""
    id_nativo = str(det.get("id") or "").strip()
    return {
        "id": f"ticketandgo:{id_nativo}",
        "fonte": "ticketandgo",
        "id_nativo": id_nativo,
        "nome": det.get("nome"),
        "start_date": _quando(det.get("inicio"), det.get("hora_incio")),
        "end_date": _quando(det.get("fim"), det.get("hora_fim")),
        # rotulados pelo filtro _do_df (a fonte não manda cidade/estado)
        "cidade": cidade_label,
        "estado": estado_label,
        "local_nome": (det.get("local") or "").strip() or None,
        "endereco": None,
        "lat": None,
        "lon": None,
        "categoria": (det.get("nome_tipo_evento") or "").strip() or None,
        "organizador": None,  # produtora é razão social (pessoa jurídica/física)
        "url": f"https://www.ticketandgo.com.br/evento/{slug}",
        "imagem": det.get("banner") or det.get("imagem") or None,
        "raspado_em": datetime.now(timezone.utc).isoformat(),
        # descrição já vem no detalhe — sem passo "descrever" p/ esta fonte
        "descricao": _limpar_html(det.get("descricao")),
        "_raw": det,  # payload bruto -> cru.ticketandgo (append-only)
        # Colunas proprias de cru.ticketandgo: a fonte NAO expoe mais endereco
        # (a V1 foi desligada), entao cidade/estado vem do _do_df da coleta; e
        # o `slug` nao e derivavel do id numerico e mudou de chave entre as
        # eras (`slug_evento` na V2, `slug` na V1). Gravar o que a coleta de
        # fato usou torna a reconstrucao independente de adivinhar a forma.
        "_cru": {"slug": slug or None, "cidade_label": cidade_label,
                 "estado_label": estado_label},
    }


def _futuro_por_dia(ev):
    """Corte grosso sobre o catálogo (que só tem DIA, sem hora): mantém o que
    termina de ontem em diante. A margem de 1 dia evita perder o evento que
    começa hoje à noite; a hora exata chega no detalhe e quem decide de fato é
    `_futuro`."""
    dia = (ev.get("fim") or ev.get("inicio") or "").strip()[:10]
    if not dia:
        return False
    ontem = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    return dia >= ontem


def _futuro(det):
    quando = _quando(det.get("fim"), det.get("hora_fim")) \
        or _quando(det.get("inicio"), det.get("hora_incio"))
    if not quando:
        return False
    try:
        return datetime.fromisoformat(quando) >= datetime.now(timezone.utc)
    except ValueError:
        return False


# Estatísticas da última chamada a raspar(), para o relatório de cobertura do
# atualizar.py (total_site = eventos DF identificados no catálogo — o recorte,
# não o total nacional).
ULTIMA_RASPAGEM = {}


def raspar(cidade_label="Brasília", estado_label="DF", pausa=0.15,
           apenas_futuros=True, locais_df=None):
    """Varre o catálogo nacional, busca o detalhe dos futuros e filtra DF.

    `locais_df` é a referência canônica de casas do DF (nomes e apelidos), que
    o pipeline lê de `curado.locais` e passa pronta — a coleta não conhece a
    base. Vazia, o filtro cai só nos sinais textuais, que já cobrem ~75%.

    Uma requisição de detalhe por evento futuro (~430 hoje, ~1,5 min com a
    pausa padrão): é o preço de a fonte ter tirado hora, descrição e endereço
    da listagem. O filtro DF só pode rodar DEPOIS do detalhe, porque o sinal
    principal (CEP na descrição) só existe lá.
    """
    # normaliza uma vez: o filtro roda ~430 vezes por rodada
    conhecidos = {_norm(x) for x in (locais_df or ()) if x}
    if not conhecidos:
        print("  (aviso: sem locais canônicos — o filtro DF cai só nos sinais "
              "textuais)")
    catalogo = _catalogo()
    if not catalogo:
        # Catálogo vazio é listagem que não chegou, não fonte sem eventos —
        # falhar alto para o pipeline não ler o silêncio como "esvaziou" e
        # esconder a agenda da fonte (NI-58/NI-59).
        raise RuntimeError("catálogo do Ticket and Go veio vazio — API mudou?")
    candidatos = {s: e for s, e in catalogo.items() if _futuro_por_dia(e)}
    print(f"  catálogo: {len(catalogo)} eventos | futuros (por dia): "
          f"{len(candidatos)} — buscando detalhe de cada um...")

    vistos, df, falhas = {}, 0, 0
    novos_locais = Counter()
    for n, slug in enumerate(candidatos, 1):
        try:
            det = _detalhe(slug)
        except Exception:
            falhas += 1
            det = None
        # a pausa é POR REQUISIÇÃO (ritmo educado com a fonte), não por evento
        # aproveitado — a maioria dos detalhes é de outra cidade e se descarta
        if pausa:
            time.sleep(pausa)
        if n % 100 == 0:
            print(f"  {n}/{len(candidatos)} detalhes | DF até aqui: {df}")
        if det is None:
            continue
        if not _do_df(det.get("local"), det.get("nome"), det.get("descricao"),
                      conhecidos):
            continue
        df += 1
        if _norm(det.get("local")) not in conhecidos:
            novos_locais[(det.get("local") or "?").strip()] += 1
        if apenas_futuros and not _futuro(det):
            continue
        norm = _normalizar(det, slug, cidade_label, estado_label)
        if norm["id_nativo"]:
            vistos.setdefault(norm["id"], norm)

    if candidatos and falhas > len(candidatos) // 2:
        # Metade dos detalhes falhando é a rota tendo mudado de novo, não azar
        # de rede — mesma lógica do catálogo vazio: falhar alto (NI-58/NI-59).
        raise RuntimeError(f"{falhas}/{len(candidatos)} detalhes falharam — "
                           f"a rota /eventos/{{slug}}/evento mudou?")
    print(f"  DF: {df} | futuros normalizados: {len(vistos)}"
          + (f" | {falhas} detalhes falharam" if falhas else ""))
    if novos_locais:
        # Fila de curadoria: estes entraram só por sinal textual. Casa
        # recorrente aqui merece virar linha de `curado.locais` — no dia em que
        # a descrição dela não repetir o endereço, ela sumiria calada. O mesmo
        # sinal vive na view curado.pendencias, que não some com o terminal.
        print("  candidatos a curado.locais (entraram por texto): "
              + "; ".join(f"{loc} ({n}x)"
                          for loc, n in novos_locais.most_common(8)))
    ULTIMA_RASPAGEM.update(total_site=df, coletados=len(vistos))
    return list(vistos.values())
