"""SPIKE — o pipeline do Sympla inteiro, escrito dagster-first.

    python src/ferramentas/dagster_dev.py --spike     # sobe junto do grafo real

Experimento, não candidato a produção. O grafo de verdade
(`src/pipeline/definitions.py`) é uma casca fina: cada asset chama um passo de
`pipeline/passos.py` e o dado anda pelo Neon, de tabela em tabela. Aqui é o
oposto declarado: **a lógica mora no próprio arquivo do Dagster e o dado passa
de asset para asset**, para dar de ver como fica um desenho em que cada etapa é
um nó com entrada e saída explícitas.

Só o Sympla, e da API pública até a estrutura que o site consome hoje — as
colunas de `tratado.eventos` e `tratado.lotes`. Escreve no schema **`spike`**
da base de **teste**: nada aqui toca `cru`, `tratado`, `curado` ou `operacao`.

**A passagem de bastão, etapa por etapa:**

    sympla/catalogo   ── list[payload] ──┐
                                         ├─→ sympla/eventos ─ list[linha] ─┐
    sympla/detalhes   ── {id: payload} ──┘                                 ├─→ spike/prata → spike/conferencia
    sympla/tickets    ── {id: payload} ──── sympla/lotes ─ {id: [lote]} ───┘

**O que é embutido, e o que não é.** A lógica do Sympla (falar com os três
endpoints, ler cada payload, montar as colunas, extrair lotes) está escrita
aqui, sem importar `coleta/sympla.py` nem `tratamento/sympla.py` — é o ponto do
experimento. O que continua vindo de `base/` é infra transversal: conexão,
parse de data e limpeza de HTML. Reimplementá-las não testaria nada do desenho
e só criaria uma segunda regra de negócio para divergir da primeira.

**O QUE ESTE DESENHO PERDE, e é o achado que ele existe para tornar visível:**

1. **Não há bronze.** O payload vive entre os assets, no IO manager, e some
   quando o run é descartado. Sem `cru`, não há reconstrução a seco (`campo
   novo = uma função + --so-derivar`, sem re-raspar), não há histórico de preço
   e não há `visto_em` — logo `raspado_em` aqui é a hora da coleta, não o
   último avistamento no catálogo, e a coluna `sumido` não teria como existir.
2. **Nada é incremental.** O `descrever` real pergunta ao cru quem ainda não
   tem detalhe; aqui a única fila possível é "todo mundo do catálogo", porque
   não existe onde consultar o que já foi buscado. Por isso o teto de
   `limite_detalhes` na config — sem ele o spike bate na fonte uma vez por
   evento a cada iteração de desenho.
3. **O dado trafega.** No grafo real isso é proibido por decisão (D8, §4.4):
   os assets passam dicionários de contagem, e o dado anda pelo banco. A razão
   é que a code location do servidor não tem volume compartilhado — o IO
   manager default grava em disco local, e um run distribuído não acharia o
   arquivo. Aqui funciona porque é tudo o mesmo processo, na mesma máquina.

Ou seja: o spike compra clareza de grafo pagando com a camada medalhão. Ler os
dois lado a lado na UI é a forma mais rápida de decidir quanto dessa clareza dá
para levar para o grafo real sem pagar esse preço.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

import dagster as dg                                              # noqa: E402

from base import conexao, tempo, texto                            # noqa: E402
# `bairros` entra pela mesma porta que `base/`: é regra do DF, não do Sympla —
# um dicionário de regiões que canoniza a grafia ("Asa Norte" tem três) e tenta
# o endereço em texto livre quando a fonte não disse. A primeira versão deste
# spike a deixou de fora, e a conferência acusou: 85 eventos com `bairro` nulo
# contra a prata real. É o tipo de perda que só aparece comparando.
from tratamento import bairros                                    # noqa: E402


# --------------------------------------------------------------------------
# guarda de base — a mesma de `src/ferramentas/dagster_dev.py`, repetida de
# propósito: um spike que escreve no banco não pode depender de outro arquivo
# ter sido carregado antes para saber em QUAL banco escreve.
# --------------------------------------------------------------------------

def _apontar_para_teste():
    url = conexao.env_var("EVENTOS_DB_URL_TESTE")
    if not url or "teste" not in url:
        raise SystemExit(
            "EVENTOS_DB_URL_TESTE ausente ou não parece a base de teste. "
            "O spike escreve no banco; sem essa garantia ele não carrega.")
    conexao.DB_URL = url
    return url


_apontar_para_teste()


class Limites(dg.Config):
    """Config do run. O teto de detalhes existe porque, sem bronze, não há fila
    incremental: cada materialização re-busca tudo o que couber no teto."""
    max_paginas: int = 10
    limite_detalhes: int = 40
    janela_tickets_dias: int = 30
    pausa_s: float = 0.4


# --------------------------------------------------------------------------
# o Sympla, embutido: os três endpoints
# --------------------------------------------------------------------------

API_CATALOGO = "https://www.sympla.com.br/api/discovery-bff/search/category-type"
BFF_EVENTO = "https://event-page.svc.sympla.com.br/api/event-bff/purchase/event/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CABECALHOS = {"User-Agent": UA, "Accept": "application/json",
              "Referer": "https://www.sympla.com.br/"}

TEMA_FESTAS_SHOWS = 99          # "Festas e Shows" — o recorte do projeto
BILETO_HOST = "bileto.sympla.com.br"   # outro namespace de id (NI-17)


def _get(url):
    req = urllib.request.Request(url, headers=CABECALHOS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _post(params):
    """A descoberta virou POST em 04/08/2026 — GET responde 405. `service` é
    obrigatório: sem ele a resposta é um HTML de erro 500."""
    req = urllib.request.Request(
        API_CATALOGO, data=json.dumps(params).encode(), method="POST",
        headers={**CABECALHOS, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _id_da_url(url):
    """O id numérico do FIM da URL pública, que é o que os BFFs de página e de
    tickets entendem — e que NÃO é o id do catálogo. URL do Bileto devolve
    None: lá o número é de outro namespace e o BFF entregaria um evento alheio
    com HTTP 200."""
    if not url or BILETO_HOST in url:
        return None
    fim = url.rstrip("/").rsplit("/", 1)[-1]
    return fim if fim.isdigit() else None


def _futuro(payload):
    fim = payload.get("end_date") or payload.get("start_date")
    try:
        return bool(fim) and datetime.fromisoformat(fim) >= datetime.now(timezone.utc)
    except ValueError:
        return False


# --------------------------------------------------------------------------
# etapa 1 — catálogo: a lista de eventos de Brasília
# --------------------------------------------------------------------------

@dg.asset(key=["sympla", "catalogo"], group_name="coleta",
          description="POST paginado na API de descoberta. Saída: a LISTA de "
                      "payloads de catálogo, um por evento futuro.")
def sympla_catalogo(context: dg.AssetExecutionContext, config: Limites):
    vistos, total_site, paginas = {}, None, 0
    for pagina in range(1, config.max_paginas + 1):
        resposta = _post({"service": "/v4/search", "city": "brasilia",
                          "state": "DF", "location": "Brasília",
                          "sort": "month-trending-score",
                          "location_score": "month-trending-score",
                          "themes": TEMA_FESTAS_SHOWS,
                          "limit": 100, "page": pagina})
        dados = resposta.get("data") or []
        total_site = resposta.get("total", total_site)
        paginas = pagina
        if not dados:
            break
        for payload in dados:
            id_nativo = str(payload.get("id") or "")
            if id_nativo and id_nativo not in vistos and _futuro(payload):
                vistos[id_nativo] = payload
        context.log.info(f"página {pagina}: +{len(dados)} | acumulado "
                         f"{len(vistos)} futuros | total no site: {total_site}")
        if len(dados) < 100:
            break
        time.sleep(config.pausa_s)

    return dg.MaterializeResult(
        value=vistos,
        metadata={"eventos": len(vistos), "paginas": paginas,
                  "total_no_site": total_site or 0,
                  "cobertura_%": round(100 * len(vistos) / total_site, 1)
                  if total_site else 0.0})


# --------------------------------------------------------------------------
# etapa 2 — detalhes: uma requisição por evento, com a guarda do NI-17
# --------------------------------------------------------------------------

@dg.asset(key=["sympla", "detalhes"], group_name="coleta",
          ins={"catalogo": dg.AssetIn(key=["sympla", "catalogo"])},
          description="BFF da página de evento, um por evento. Saída: "
                      "{id_nativo: payload}. Guarda de nome antes de aceitar: "
                      "id de outro namespace devolve evento alheio sem erro.")
def sympla_detalhes(context: dg.AssetExecutionContext, config: Limites,
                    catalogo):
    fila = [(i, p) for i, p in catalogo.items() if _id_da_url(p.get("url"))]
    sem_id = len(catalogo) - len(fila)
    fila = fila[:config.limite_detalhes]

    saida, falhas, trocados = {}, [], 0
    for id_nativo, payload in fila:
        try:
            detalhe = _get(f"{BFF_EVENTO}{_id_da_url(payload['url'])}")
        except Exception as e:                                   # noqa: BLE001
            falhas.append({"evento": id_nativo, "erro": f"{type(e).__name__}: {e}"})
            continue
        # A guarda só vale FRESCA: compara o nome que o BFF acabou de devolver
        # com o do catálogo desta mesma rodada. Repeti-la na leitura reprovaria
        # descrição boa toda vez que o produtor renomeia o evento.
        if detalhe.get("name") and not texto.mesmo_nome(payload.get("name"),
                                                        detalhe["name"]):
            trocados += 1
            falhas.append({"evento": id_nativo,
                           "erro": f"nome divergente: {detalhe['name']!r}"})
            continue
        saida[id_nativo] = detalhe
        time.sleep(config.pausa_s)

    context.log.info(f"{len(saida)} detalhes; {trocados} reprovados na guarda; "
                     f"{sem_id} sem id na URL (Bileto ou URL sem número)")
    return dg.MaterializeResult(
        value=saida,
        metadata={"buscados": len(saida), "reprovados_guarda": trocados,
                  "sem_id_na_url": sem_id, "falhas": len(falhas),
                  "teto_da_config": config.limite_detalhes,
                  "fila_completa_seria": len(catalogo) - sem_id})


# --------------------------------------------------------------------------
# etapa 3 — tickets: preço e lotes, só de quem tem detalhe
# --------------------------------------------------------------------------

@dg.asset(key=["sympla", "tickets"], group_name="coleta",
          ins={"catalogo": dg.AssetIn(key=["sympla", "catalogo"]),
               "detalhes": dg.AssetIn(key=["sympla", "detalhes"])},
          description="BFF de tickets. Depende de `detalhes` por GUARDA, não "
                      "por dado: este endpoint não devolve o nome do evento, "
                      "então o detalhe aprovado é a âncora contra id trocado.")
def sympla_tickets(context: dg.AssetExecutionContext, config: Limites,
                   catalogo, detalhes):
    limite = datetime.now(timezone.utc) + timedelta(
        days=config.janela_tickets_dias)
    alvos, fora_janela = [], 0
    for id_nativo in detalhes:
        inicio = tempo.instante((catalogo[id_nativo] or {}).get("start_date"))
        if not inicio:
            continue
        if inicio > limite:
            fora_janela += 1
            continue
        alvos.append(id_nativo)

    saida, falhas = {}, []
    for id_nativo in alvos:
        try:
            saida[id_nativo] = _get(
                f"{BFF_EVENTO}{_id_da_url(catalogo[id_nativo]['url'])}/tickets")
        except Exception as e:                                   # noqa: BLE001
            falhas.append({"evento": id_nativo, "erro": f"{type(e).__name__}: {e}"})
        time.sleep(config.pausa_s)

    context.log.info(f"{len(saida)} payloads de tickets; {fora_janela} eventos "
                     f"fora da janela de {config.janela_tickets_dias} dias")
    return dg.MaterializeResult(
        value=saida,
        metadata={"buscados": len(saida), "fora_janela": fora_janela,
                  "falhas": len(falhas)})


# --------------------------------------------------------------------------
# etapa 4 — eventos: a seco, payload → colunas do schema unificado
# --------------------------------------------------------------------------

COLUNAS = ["id", "fonte", "id_nativo", "nome", "start_date", "end_date",
           "cidade", "estado", "local_nome", "endereco", "lat", "lon",
           "categoria", "organizador", "url", "imagem", "raspado_em",
           "descricao", "atracoes", "preco_min",
           "bairro", "popularidade", "esgotado", "cancelado", "tem_gratis"]


def _identidade(payload, id_nativo):
    """Payload de catálogo → as colunas de identidade. Devolve None quando o
    id do payload não bate com a chave: numa troca de API, o parser novo sobre
    o payload velho não falha — acha campos homônimos e degrada em silêncio."""
    if str(payload.get("id") or "") != id_nativo:
        return None
    local = payload.get("location") or {}
    imagens = payload.get("images") or {}
    bairro = (local.get("neighborhood") or "").strip()
    score = payload.get("global_score")
    return {
        "nome": payload.get("name"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "cidade": local.get("city") or None,
        "estado": local.get("state") or None,
        "local_nome": local.get("name") or None,
        "endereco": local.get("address") or None,
        "lat": local.get("lat") or None,
        "lon": local.get("lon") or None,
        "organizador": (payload.get("organizer") or {}).get("name") or None,
        "url": payload.get("url"),
        "imagem": imagens.get("lg") or imagens.get("original") or None,
        "bairro": bairro or None,
        "popularidade": score if isinstance(score, (int, float)) else None,
    }


def _do_detalhe(payload):
    """Payload do BFF de página → as colunas que só ele tem.

    `categoria` vem daqui e SÓ daqui: o `event_type` do catálogo é 'NORMAL' em
    100% dos eventos — flag de modalidade, não categoria — e sobrescrevia este
    valor a cada rodada."""
    categoria = payload.get("eventsCategory")
    if isinstance(categoria, dict):
        categoria = categoria.get("name")
    return {"cancelado": 1 if payload.get("cancelled") else 0,
            "descricao": (texto.limpar_html(payload.get("detail"))
                          or texto.limpar_html(payload.get("strippedDetail"))),
            "categoria": categoria.strip()
            if isinstance(categoria, str) and categoria.strip() else None}


@dg.asset(key=["sympla", "eventos"], group_name="tratamento",
          ins={"catalogo": dg.AssetIn(key=["sympla", "catalogo"]),
               "detalhes": dg.AssetIn(key=["sympla", "detalhes"])},
          description="A seco: catálogo + detalhe → uma linha por evento no "
                      "schema unificado. Nenhuma requisição de rede.")
def sympla_eventos(context: dg.AssetExecutionContext, catalogo, detalhes):
    agora = datetime.now(timezone.utc).isoformat()
    linhas, rejeitados = [], []
    for id_nativo, payload in catalogo.items():
        base = _identidade(payload, id_nativo)
        if base is None:
            rejeitados.append({"evento": id_nativo,
                               "erro": "id do payload não bate com a chave"})
            continue
        if not base.get("nome") or not base.get("url"):
            rejeitados.append({"evento": id_nativo, "erro": "sem nome ou url"})
            continue
        linha = dict.fromkeys(COLUNAS)
        linha.update(base)
        linha.update({"id": f"sympla:{id_nativo}", "fonte": "sympla",
                      "id_nativo": id_nativo,
                      # Sem bronze não há `visto_em`: aqui isto é a hora da
                      # coleta, e não "a última vez que o evento apareceu no
                      # catálogo" — que é o que a coluna significa na prata.
                      "raspado_em": agora})
        if id_nativo in detalhes:
            linha.update({c: v for c, v in _do_detalhe(detalhes[id_nativo]).items()
                          if v is not None})
        # Último passo da composição, e o único lugar em que `bairro` se
        # resolve: um segundo escritor desta coluna seria o desenho que
        # produziu o bug histórico da `categoria`.
        linha["bairro"] = (bairros.canonizar(linha.get("bairro"))
                           or bairros.extrair(linha.get("endereco")))
        linhas.append(linha)

    return dg.MaterializeResult(
        value=linhas,
        metadata={"eventos": len(linhas), "com_descricao":
                  sum(1 for x in linhas if x["descricao"]),
                  "com_categoria": sum(1 for x in linhas if x["categoria"]),
                  "com_coordenada": sum(1 for x in linhas if x["lat"]),
                  "rejeitados": len(rejeitados),
                  "rejeitados_texto": dg.MarkdownMetadataValue(
                      "\n".join(f"- `{r['evento']}` — {r['erro']}"
                                for r in rejeitados[:10]) or "—")})


# --------------------------------------------------------------------------
# etapa 5 — lotes: a seco, payload de tickets → linhas de lote
# --------------------------------------------------------------------------

@dg.asset(key=["sympla", "lotes"], group_name="tratamento",
          ins={"tickets": dg.AssetIn(key=["sympla", "tickets"])},
          description="A seco: tickets → lotes. O nome do lote fica CRU de "
                      "propósito — a condição ('CORTESIA FEMININA ATÉ 00H') é "
                      "para um agente ler, não para regex.")
def sympla_lotes(context: dg.AssetExecutionContext, tickets):
    saida = {}
    for id_nativo, payload in tickets.items():
        lotes = []
        for t in (payload.get("tickets") or []):
            if not isinstance(t, dict) or t.get("show") is False:
                continue
            gratis = bool(t.get("isFree"))
            preco = 0.0 if gratis else None
            if not gratis:
                for chave in ("salePriceWithDiscountMonetary",
                              "salePriceMonetary"):
                    # `.decimal` já vem em R$ COM a taxa embutida:
                    # 49,50 = 45,00 + 4,50, e `feeMonetary` traz a taxa à parte.
                    v = (t.get(chave) or {}).get("decimal")
                    if isinstance(v, (int, float)):
                        preco = float(v)
                        break
            taxa = (t.get("feeMonetary") or {}).get("decimal")
            lotes.append({
                "nome": t.get("name"), "preco": preco,
                "taxa": float(taxa) if isinstance(taxa, (int, float)) else None,
                "gratis": 1 if gratis else 0,
                "esgotado": 1 if (t.get("currentAvailableQty") or 0) == 0 else 0})
        if lotes:
            saida[id_nativo] = lotes

    total = sum(len(v) for v in saida.values())
    return dg.MaterializeResult(
        value=saida,
        metadata={"eventos_com_lote": len(saida), "lotes": total,
                  "eventos_sem_lote": len(tickets) - len(saida)})


# --------------------------------------------------------------------------
# etapa 6 — prata: junta, resume os lotes e escreve
# --------------------------------------------------------------------------

DDL = """
CREATE SCHEMA IF NOT EXISTS spike;

CREATE TABLE IF NOT EXISTS spike.eventos (
    id TEXT PRIMARY KEY, fonte TEXT NOT NULL, id_nativo TEXT NOT NULL,
    nome TEXT NOT NULL, start_date TEXT, end_date TEXT,
    cidade TEXT, estado TEXT, local_nome TEXT, endereco TEXT,
    lat DOUBLE PRECISION, lon DOUBLE PRECISION,
    categoria TEXT, organizador TEXT, url TEXT, imagem TEXT,
    raspado_em TEXT NOT NULL, descricao TEXT, atracoes TEXT,
    preco_min DOUBLE PRECISION, bairro TEXT, popularidade INTEGER,
    esgotado INTEGER, cancelado INTEGER, tem_gratis INTEGER
);

CREATE TABLE IF NOT EXISTS spike.lotes (
    evento_id TEXT NOT NULL, ordem INTEGER NOT NULL, nome TEXT,
    preco DOUBLE PRECISION, taxa DOUBLE PRECISION,
    gratis INTEGER NOT NULL, esgotado INTEGER
);
"""


def _resumo_dos_lotes(lotes):
    """As três colunas de evento que resumem os lotes. Leitura combinada:
    preco_min=38.99 + tem_gratis=1 -> "grátis em condições, pagos a partir de
    R$ 38,99"; preco_min NULL + tem_gratis=1 -> evento grátis."""
    pagos = [x["preco"] for x in lotes if not x["gratis"] and x["preco"] is not None]
    return {"preco_min": min(pagos) if pagos else None,
            "tem_gratis": 1 if any(x["gratis"] and x["esgotado"] != 1
                                   for x in lotes) else 0,
            "esgotado": 1 if all(x["esgotado"] == 1 for x in lotes) else 0}


@dg.asset(key=["spike", "prata"], group_name="carga",
          ins={"eventos": dg.AssetIn(key=["sympla", "eventos"]),
               "lotes": dg.AssetIn(key=["sympla", "lotes"])},
          description="Escreve `spike.eventos` e `spike.lotes` numa transação "
                      "só. As transformações de escrita (data em ISO UTC, "
                      "título limpo) moram AQUI, no único ponto que grava.")
def spike_prata(context: dg.AssetExecutionContext, eventos, lotes):
    linhas = []
    for linha in eventos:
        linha = dict(linha)
        do_evento = lotes.get(linha["id_nativo"])
        if do_evento:
            linha.update(_resumo_dos_lotes(do_evento))
        # O invariante mora no ponto de escrita, não em quem chama: data em ISO
        # UTC "+00:00" (a comparação no SQL é lexical) e nome limpo — o mesmo
        # texto que vira <h1>, FTS e slug, que por isso não podem divergir.
        for coluna in ("start_date", "end_date", "raspado_em"):
            linha[coluna] = tempo.norm_ts(linha[coluna])
        linha["nome"] = texto.titulo_limpo(linha["nome"])
        linhas.append(linha)

    con = conexao.conectar()
    try:
        with con.cursor() as cur:
            cur.execute(DDL)
            # DELETE e não TRUNCATE, pela mesma razão do ciclo real: TRUNCATE
            # toma ACCESS EXCLUSIVE e faria um leitor BLOQUEAR em vez de ver a
            # versão anterior. Aqui ninguém lê, mas o hábito é o que se testa.
            cur.execute("DELETE FROM spike.lotes")
            cur.execute("DELETE FROM spike.eventos")
            cur.executemany(
                f"INSERT INTO spike.eventos ({','.join(COLUNAS)}) "
                f"VALUES ({','.join('%s' for _ in COLUNAS)})",
                [[linha.get(c) for c in COLUNAS] for linha in linhas])
            cur.executemany(
                "INSERT INTO spike.lotes (evento_id, ordem, nome, preco, taxa, "
                "gratis, esgotado) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [(f"sympla:{id_nativo}", ordem, x["nome"], x["preco"],
                  x["taxa"], x["gratis"], x["esgotado"])
                 for id_nativo, do_evento in lotes.items()
                 for ordem, x in enumerate(do_evento)])
            base = con.info.dbname
        con.commit()
    finally:
        con.close()

    return dg.MaterializeResult(metadata={
        "base": base, "eventos": len(linhas),
        "lotes": sum(len(v) for v in lotes.values()),
        "com_preco": sum(1 for x in linhas if x["preco_min"] is not None)})


# --------------------------------------------------------------------------
# etapa 7 — conferência: o spike bate com a prata de verdade?
# --------------------------------------------------------------------------

# Colunas que divergem por CONSTRUÇÃO, não por erro: o spike coleta agora
# (`raspado_em`), tem teto de detalhes (`descricao`, `categoria`, `cancelado`)
# e janela própria de tickets (as três de preço).
ESPERADAS = {"raspado_em", "descricao", "categoria", "cancelado",
             "preco_min", "tem_gratis", "esgotado"}


@dg.asset(key=["spike", "conferencia"], group_name="carga",
          deps=[dg.AssetKey(["spike", "prata"])],
          description="Compara `spike.eventos` com o que o pipeline real "
                      "produziu em `tratado.eventos` para o Sympla. Divergência "
                      "inesperada é defeito do spike OU a fonte tendo mudado "
                      "desde a última rodada real — as duas causas valem olhar.")
def spike_conferencia(context: dg.AssetExecutionContext):
    con = conexao.conectar()
    try:
        spike = {r["id"]: dict(r) for r in
                 con.execute("SELECT * FROM spike.eventos").fetchall()}
        real = {r["id"]: dict(r) for r in con.execute(
            "SELECT * FROM tratado.eventos WHERE fonte = 'sympla'").fetchall()}
    finally:
        con.close()

    comuns = set(spike) & set(real)
    divergentes = {}
    for id_evento in comuns:
        for coluna in COLUNAS:
            if spike[id_evento].get(coluna) != real[id_evento].get(coluna):
                divergentes.setdefault(coluna, []).append(id_evento)

    inesperadas = {c: v for c, v in divergentes.items() if c not in ESPERADAS}
    tabela = ["| coluna | linhas | esperada? |", "| --- | --- | --- |"]
    for coluna, ids in sorted(divergentes.items(), key=lambda x: -len(x[1])):
        tabela.append(f"| `{coluna}` | {len(ids)} | "
                      f"{'sim' if coluna in ESPERADAS else '**NÃO**'} |")

    return dg.MaterializeResult(metadata={
        "no_spike": len(spike), "na_prata_real": len(real),
        "em_comum": len(comuns),
        "só_no_spike": len(set(spike) - set(real)),
        "só_na_prata": len(set(real) - set(spike)),
        "colunas_divergentes": len(divergentes),
        "divergencias_inesperadas": len(inesperadas),
        "comparacao": dg.MarkdownMetadataValue("\n".join(tabela))})


ASSETS = [sympla_catalogo, sympla_detalhes, sympla_tickets,
          sympla_eventos, sympla_lotes, spike_prata, spike_conferencia]

pipeline_sympla = dg.define_asset_job("spike_sympla",
                                      selection=dg.AssetSelection.all(),
                                      tags={"dagster/max_runtime": 1800})

defs = dg.Definitions(assets=ASSETS, jobs=[pipeline_sympla])
