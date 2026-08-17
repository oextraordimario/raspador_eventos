"""O grafo de assets do Dagster — o ÚNICO arquivo do projeto que importa
`dagster` (spec 20260814_orquestracao-dagster §5.1).

O Dagster entra como mais um chamador de `pipeline/passos.py`, na mesma posição
que o `atualizar.py` ocupa: aqui não há regra de negócio, só a ORDEM em que os
passos são chamados, o que fazer quando um falha, e o que vira metadata na tela.
Se o homelab não vingar, apaga-se este arquivo e o CLI segue rodando.

**O que o grafo diz, e o CLI não dizia** (é o motivo nº 1 da migração): cada
fonte é um nó. Quando o Sympla morre, o Sympla fica vermelho e o resto do run
segue — em vez de uma rodada inteira marcada "success" com uma fonte muda
dentro, que foi o que escondeu 180 eventos parados por sete dias (§1.3).

Chaves com prefixo de camada (`cru/…`, `tratado/…`, `operacao/…`): a AssetKey
espelha o schema onde o dado cai, e o grafo se lê como a arquitetura.

**Duas regras que este arquivo não pode violar:**

1. Nenhum asset abre transação própria sobre `tratado`. Quem escreve na prata é
   `ciclo.executar`, numa transação só, com DELETE e não TRUNCATE — porque
   `public` é view sobre `tratado` e o site consulta enquanto isso roda (§4.3).
2. Os assets NÃO trafegam dado de verdade. O dado anda pelo Neon; o que passa
   de um asset para outro é o dicionário de resultado (contagens, erros,
   duração), algumas centenas de bytes que o relatório e `operacao.execucoes`
   consomem no formato exato de hoje (§4.4, D8).

Consequência a não esquecer: **re-materializar um asset de coleta não restaura
nada** — ele vai à fonte de novo, e a fonte só sabe do presente. "Materialize"
é gatilho, nunca retrocesso.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# O Dagster carrega este arquivo por caminho absoluto (`dagster api grpc -f`),
# e isso NÃO põe `src/` no sys.path como um entrypoint faria. O container ainda
# define PYTHONPATH, mas esta linha é o que faz o arquivo carregar em qualquer
# lugar (ensaio local, `dg dev`, teste) — idempotente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dagster as dg                                              # noqa: E402

from base import conexao                                          # noqa: E402
from coleta import gravar                                         # noqa: E402
from pipeline import execucoes, passos                            # noqa: E402
from tratamento import ciclo, curadoria                           # noqa: E402

# Re-tentar coleta é seguro: o `cru` é append-only com dedupe por hash, então
# payload igual não vira linha nova. NÃO vale para a extração de flyer, que
# gasta cota da assinatura por tentativa (§5.3).
RETRY_REDE = dg.RetryPolicy(max_retries=2, delay=30,
                            backoff=dg.Backoff.EXPONENTIAL)

# Pool das etapas que falam com a internet (§7.2). Sem limite configurado na
# instância o pool não restringe nada — ele existe para que o dia em que uma
# fonte precisar de trava, a trava seja uma linha no `dagster.yaml` e não uma
# mudança de código.
POOL_REDE = "rede"

MODO = "dagster"


def _k(*partes):
    return dg.AssetKey(list(partes))


def _escalares(dic):
    """Só o que a UI sabe mostrar. Um `None` viraria célula vazia sem explicar
    se o passo não rodou ou devolveu nada — vira string."""
    saida = {}
    for chave, valor in (dic or {}).items():
        if valor is None:
            saida[chave] = ""
        elif isinstance(valor, (int, float, str)):   # bool é int, e vale igual
            saida[chave] = valor
    return saida


def _resultado(res, erros, duracao_s, extras=None):
    """O par que todo asset devolve: `value` para quem vem depois (D8) e
    `metadata` para quem está olhando a tela."""
    meta = {**_escalares(res), "duracao_s": round(duracao_s, 1),
            "erros": len(erros), **(extras or {})}
    return dg.MaterializeResult(value={"res": res, "erros": list(erros)},
                                metadata=meta)


# --------------------------------------------------------------------------
# preparação
# --------------------------------------------------------------------------

@dg.asset(key=["operacao", "schema"], group_name="preparacao",
          description="Aplica o DDL de `sql/` e recusa base de schema antigo. "
                      "É o `conectar(aplicar_schema=True)` que hoje só o "
                      "`atualizar.py` faz — no grafo ele vira o nó de que "
                      "todo o resto depende.")
def operacao_schema(context: dg.AssetExecutionContext):
    marca = time.perf_counter()
    con = conexao.conectar(aplicar_schema=True)
    try:
        # `checar_schema` chama `sys.exit` — no CLI isso é a coisa certa, aqui
        # mataria o processo do run sem explicar nada na UI.
        try:
            passos.checar_schema(con)
        except SystemExit as e:
            raise dg.Failure(description=str(e)) from None
        base = con.info.dbname
    finally:
        con.close()
    return dg.MaterializeResult(
        value={"res": {"base": base}, "erros": []},
        metadata={"base": base, "duracao_s": round(time.perf_counter() - marca, 1)})


# --------------------------------------------------------------------------
# coleta — uma fonte, um asset (o ponto da migração)
# --------------------------------------------------------------------------

def _asset_de_fonte(nome):
    @dg.asset(key=["cru", nome], group_name="coleta",
              deps=[_k("operacao", "schema")], pool=POOL_REDE,
              retry_policy=RETRY_REDE,
              description=f"`passos.coletar('{nome}')`: fala com a fonte e "
                          f"grava o payload em `cru.{nome}` + a linha de "
                          f"`operacao.coletas`. Nunca escreve em `tratado`.")
    def _asset(context: dg.AssetExecutionContext):
        # A referência canônica de casas do DF só existe para o Ticket and Go,
        # que não expõe endereço: o filtro `_do_df` depende dela. As outras
        # fontes não abrem conexão antes da rede à toa.
        locais = ()
        if nome == "ticketandgo":
            con = conexao.conectar()
            try:
                locais = curadoria.nomes_df(con)
            finally:
                con.close()
        marca = time.perf_counter()
        res = passos.coletar(nome, locais_df=locais)
        # D6: fonte quebrada NÃO derruba o run. `passos.coletar` já devolve
        # `{"erro": ...}` em vez de levantar, e o asset materializa com o erro
        # na metadata — é o que faz uma fonte morta não esconder as outras.
        if res.get("erro"):
            context.log.error(f"[{nome}] {res['erro']}")
        return _resultado(res, [], time.perf_counter() - marca)

    return _asset


ASSETS_FONTE = [_asset_de_fonte(n) for n in passos.ORDEM_FONTES]


@dg.asset(key=["cru", "detalhes"], group_name="coleta", pool=POOL_REDE,
          retry_policy=RETRY_REDE,
          deps=[_k("cru", "sympla"), _k("cru", "ingresse"), _k("cru", "zig")],
          description="`passos.descrever`: payload de detalhe dos eventos que "
                      "ainda não têm (fila lida do CRU, nunca da prata). "
                      "Shotgun e Ticket and Go não precisam — já trazem "
                      "descrição no catálogo.")
def cru_detalhes(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        res = passos.descrever(con, erros)
    finally:
        con.close()
    return _resultado(res, erros, time.perf_counter() - marca)


@dg.asset(key=["cru", "tickets"], group_name="coleta", pool=POOL_REDE,
          retry_policy=RETRY_REDE,
          deps=[_k("cru", "detalhes"), _k("cru", "ticketandgo")],
          description="`passos.precificar`: payload de tickets dos futuros na "
                      "janela de 30 dias. Depende de `cru/detalhes` porque no "
                      "Sympla o detalhe é a âncora contra id trocado (NI-17).")
def cru_tickets(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        res = passos.precificar(con, erros)
    finally:
        con.close()
    return _resultado(res, erros, time.perf_counter() - marca)


@dg.asset(key=["cru", "cinema"], group_name="coleta", pool=POOL_REDE,
          retry_policy=RETRY_REDE, deps=[_k("operacao", "schema")],
          description="`passos.coletar_cinema`: a grade dos 8 cinemas na API "
                      "da Ingresso.com. 404 num dia é dia sem sessão, não é "
                      "erro.")
def cru_cinema(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    res = passos.coletar_cinema(erros)
    if res.get("erro"):
        context.log.error(f"[cinema] {res['erro']}")
    return _resultado(res, erros, time.perf_counter() - marca)


@dg.asset(key=["cru", "instagram"], group_name="coleta", pool=POOL_REDE,
          retry_policy=RETRY_REDE, deps=[_k("operacao", "schema")],
          description="`passos.coletar_instagram`: posts e stories da "
                      "watchlist via Monid, SEM a visão. Custa ~$0,006 por "
                      "perfil — é o primeiro custo recorrente do projeto.")
def cru_instagram(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    res = passos.coletar_instagram(erros)
    if res is None:
        # Watchlist vazia não é erro: é fonte ausente. O asset materializa
        # verde com a contagem zerada, e quem lê a tela vê a diferença.
        context.log.warning("watchlist vazia ou ausente — nada a coletar")
        res = {"perfis": 0}
    elif res.get("erro"):
        context.log.error(f"[instagram] {res['erro']}")
    return _resultado(res, erros, time.perf_counter() - marca)


@dg.asset(key=["cru", "extracao_flyer"], group_name="coleta", pool=POOL_REDE,
          deps=[_k("cru", "instagram")],
          description="`passos.extrair_flyers`: a visão (`claude -p`, na "
                      "ASSINATURA) lendo legenda + carrossel. SEM retry de "
                      "propósito: cada tentativa gasta cota, e a fila é "
                      "incremental — o que falha volta na próxima rodada.")
def cru_extracao_flyer(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    res = passos.extrair_flyers(erros)
    return _resultado(res, erros, time.perf_counter() - marca)


@dg.asset(key=["operacao", "midias"], group_name="coleta", pool=POOL_REDE,
          retry_policy=RETRY_REDE, deps=[_k("cru", "extracao_flyer")],
          description="`passos.subir_midias_instagram`: o flyer vai para o "
                      "storage próprio ANTES do tratamento, porque é a "
                      "derivação que grava a URL em `eventos.imagem`.")
def operacao_midias(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        n = passos.subir_midias_instagram(con, erros)
    finally:
        con.close()
    return _resultado({"subidas": n}, erros, time.perf_counter() - marca)


# --------------------------------------------------------------------------
# tratamento — UM compute, três assets (§4.3)
# --------------------------------------------------------------------------

_DEPS_EVENTOS = {_k("cru", "tickets"), _k("cru", "shotgun"),
                 _k("operacao", "midias")}
_DEPS_CINEMA = {_k("cru", "cinema")}

# `outs` + `internal_asset_deps`, e não `specs`: spec só aceita output do tipo
# `Nothing`, e o ciclo precisa ENTREGAR sua saída para o fecho da rodada (é o
# que o relatório e `operacao.execucoes` consomem). O `internal_asset_deps` é o
# que preserva a linhagem fina — sem ele os três assets herdariam as quatro
# dependências, e o grafo diria que a grade de cinema vem do Sympla.
@dg.multi_asset(
    name="tratamento",
    outs={
        "eventos": dg.AssetOut(
            key=["tratado", "eventos"],
            description="O schema unificado das 5 plataformas + Instagram, "
                        "reconstruído do cru."),
        "filmes": dg.AssetOut(
            key=["tratado", "filmes"],
            description="Domínio próprio do cinema (o id do filme é estável e "
                        "é a PK)."),
        "sessoes": dg.AssetOut(
            key=["tratado", "sessoes"],
            description="SNAPSHOT: sessão não tem id estável entre semanas — "
                        "sem upsert, sem dedupe, sem `sumido`."),
    },
    deps=list(_DEPS_EVENTOS | _DEPS_CINEMA),
    internal_asset_deps={"eventos": _DEPS_EVENTOS, "filmes": _DEPS_CINEMA,
                         "sessoes": _DEPS_CINEMA},
    group_name="tratamento", can_subset=False,
)
def tratamento(context: dg.AssetExecutionContext):
    """`ciclo.executar`: oito passos a seco e UM commit.

    Três assets, um compute só. Quebrar isto em oito assets significaria oito
    commits — e uma janela em que o site serve "nenhum evento encontrado"
    enquanto a prata se reconstrói. A spec do medalhão §8.1 já pagou para
    aprender; o grafo ganha granularidade visual sem que a transação mude.
    """
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        saida = ciclo.executar(con)
    finally:
        con.close()
    duracao = round(time.perf_counter() - marca, 1)
    derivado, enriq = saida["derivado"], saida["enriquecimento"]
    cine, insta = saida["cinema"], saida["instagram"]

    # `derivado` é {coluna: quantos eventos ganharam valor} — 23 chaves, que na
    # tela viram ruído. Fica o que responde "a rodada foi normal?": o total
    # (todo evento tem nome, a guarda exige), o que a guarda REPROVOU, e a
    # cobertura dos três campos que o site usa e que costumam degradar.
    derivado = derivado or {}
    yield dg.Output(
        saida, output_name="eventos",
        metadata={"eventos": derivado.get("nome", 0),
                  "lotes": derivado.get("lotes", 0),
                  "rejeitados": len(derivado.get("rejeitados") or []),
                  "com_preco": derivado.get("preco_min", 0),
                  "com_local": derivado.get("local_nome", 0),
                  "com_coordenada": derivado.get("lat", 0),
                  "duracao_s": duracao,
                  "ruido": len(enriq["ruido"]),
                  "dedupe_grupos": len(enriq["grupos"]),
                  "sumidos": len(saida["sumidos"] or []),
                  "instagram_eventos": (insta or {}).get("eventos", 0),
                  "curadoria_aplicadas": saida["curadoria"]["aplicadas"],
                  "slugs_desempates": len(saida["slugs"]["desempates"])})
    yield dg.Output(cine, output_name="filmes",
                    metadata={**_escalares(cine), "duracao_s": duracao})
    yield dg.Output(cine, output_name="sessoes",
                    metadata={**_escalares(cine), "duracao_s": duracao})


# --------------------------------------------------------------------------
# enriquecimento — a segunda volta. Grupo próprio, e não "tratamento", porque
# os dois primeiros ABREM REDE: pô-los junto do ciclo desmentiria na tela a
# fronteira que o projeto inteiro serve (rede é coleta, a seco é tratamento).
# --------------------------------------------------------------------------

@dg.asset(key=["cru", "tmdb"], group_name="enriquecimento", pool=POOL_REDE,
          retry_policy=RETRY_REDE, deps=[_k("tratado", "filmes")],
          description="`passos.enriquecer_cinema`: sinopse/nota/ano por filme "
                      "NOVO. Fica DEPOIS do tratamento porque a lista do que "
                      "está em cartaz É a tabela `tratado.filmes` — não há "
                      "como montá-la antes (§4.5).")
def cru_tmdb(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        n = passos.enriquecer_cinema(con, erros)
    finally:
        con.close()
    return _resultado({"buscados": n}, erros, time.perf_counter() - marca)


@dg.asset(key=["operacao", "posters"], group_name="enriquecimento", pool=POOL_REDE,
          retry_policy=RETRY_REDE, deps=[_k("tratado", "filmes")],
          description="`passos.copiar_posters`: pôster do filme re-hospedado "
                      "no storage próprio, com pathname estável.")
def operacao_posters(context: dg.AssetExecutionContext):
    erros = []
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        n = passos.copiar_posters(con, erros)
    finally:
        con.close()
    return _resultado({"copiados": n}, erros, time.perf_counter() - marca)


@dg.asset(key=["tratado", "refresh"], group_name="enriquecimento",
          ins={"saida": dg.AssetIn(key=_k("tratado", "eventos")),
               "tmdb": dg.AssetIn(key=_k("cru", "tmdb")),
               "posters": dg.AssetIn(key=_k("operacao", "posters"))},
          description="O segundo `ciclo.executar`, e SÓ quando TMDB ou pôster "
                      "trouxeram algo — é o laço da §4.5 desenhado como nó em "
                      "vez de escondido dentro de um compute. Devolve a saída "
                      "do ciclo que vale para o relatório.")
def tratado_refresh(context: dg.AssetExecutionContext, saida, tmdb, posters):
    novos = (tmdb["res"].get("buscados") or 0) + (posters["res"].get("copiados") or 0)
    if not novos:
        context.log.info("nada novo de TMDB/pôster — o ciclo não roda de novo")
        return dg.MaterializeResult(value=saida,
                                    metadata={"novos": 0, "reciclou": False})
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        nova = ciclo.executar(con)
    finally:
        con.close()
    return dg.MaterializeResult(
        value=nova, metadata={"novos": novos, "reciclou": True,
                              "duracao_s": round(time.perf_counter() - marca, 1)})


# --------------------------------------------------------------------------
# fecho da rodada
# --------------------------------------------------------------------------

@dg.asset(key=["cru", "podado"], group_name="fecho",
          deps=[_k("tratado", "refresh")],
          description="`gravar.podar_historico`: única exceção ao "
                      "'nada é apagado' no cru, e só de versão INTERMEDIÁRIA "
                      "com mais de 90 dias — a mais recente de cada chave "
                      "nunca casa a condição.")
def cru_podado(context: dg.AssetExecutionContext):
    marca = time.perf_counter()
    con = conexao.conectar()
    try:
        podados = gravar.podar_historico(con, passos.JANELA_HISTORICO_DIAS)
    finally:
        con.close()
    return _resultado({"linhas": sum(podados.values()) if podados else 0},
                      [], time.perf_counter() - marca,
                      extras={"por_fonte": str(podados or {})})


_INS_EXECUCAO = {
    **{n: dg.AssetIn(key=_k("cru", n)) for n in passos.ORDEM_FONTES},
    "detalhes": dg.AssetIn(key=_k("cru", "detalhes")),
    "tickets": dg.AssetIn(key=_k("cru", "tickets")),
    "cinema": dg.AssetIn(key=_k("cru", "cinema")),
    "instagram": dg.AssetIn(key=_k("cru", "instagram")),
    "extracao": dg.AssetIn(key=_k("cru", "extracao_flyer")),
    "midias": dg.AssetIn(key=_k("operacao", "midias")),
    "tmdb": dg.AssetIn(key=_k("cru", "tmdb")),
    "posters": dg.AssetIn(key=_k("operacao", "posters")),
    "podado": dg.AssetIn(key=_k("cru", "podado")),
    "saida": dg.AssetIn(key=_k("tratado", "refresh")),
}


def _inicio_do_run(context):
    """Quando o run começou, em epoch. É o que dá a duração TOTAL da rodada —
    somar a duração dos assets daria outro número (eles rodam em paralelo)."""
    try:
        registro = context.instance.get_run_record_by_id(context.run_id)
        return registro.start_time or registro.create_timestamp.timestamp()
    except Exception:                                            # noqa: BLE001
        return None


@dg.asset(key=["operacao", "execucao"], group_name="fecho",
          ins=_INS_EXECUCAO,
          description="O fecho: relatório de saúde (com o alerta de queda > "
                      "50% vs. a rodada anterior) e a linha em "
                      "`operacao.execucoes`. Recebe o dicionário de resultado "
                      "de cada asset — é o D8, e é o formato que o "
                      "`coleta_anterior` consome.")
def operacao_execucao(context: dg.AssetExecutionContext, **entradas):
    inicio = _inicio_do_run(context)
    duracao = (time.time() - inicio) if inicio else 0.0
    iniciada_em = (
        datetime.fromtimestamp(inicio, timezone.utc).isoformat() if inicio
        else datetime.now(timezone.utc).isoformat())

    erros = [e for v in entradas.values() for e in (v or {}).get("erros", [])]
    resultados = {n: entradas[n]["res"] for n in passos.ORDEM_FONTES}
    resultados["cinema"] = entradas["cinema"]["res"]
    # O Instagram é UMA fonte para o relatório, mesmo sendo dois assets aqui:
    # coleta e visão têm custo, falha e cota diferentes, mas quem lê o
    # relatório quer a linha "instagram" inteira, como o CLI sempre mostrou.
    resultados["instagram"] = {**(entradas["instagram"]["res"] or {}),
                               **(entradas["extracao"]["res"] or {})}

    saida = entradas["saida"]      # a do refresh: é a que vale se o ciclo rodou 2x
    derivado, enriq = saida["derivado"], saida["enriquecimento"]
    sumidos = saida["sumidos"]

    desempates = saida["slugs"]["desempates"]
    if desempates:
        # Desempate de slug não é rotina: quando aparece, é sintoma (dedupe
        # frouxo ou teto de comprimento agressivo).
        print(f"\n[slug] {len(desempates)} endereço(s) precisaram de desempate:")
        for d in desempates[:10]:
            print(f"  - {d['id']} -> /{d['slug']}")
    cur = saida["curadoria"]
    if cur["aplicadas"] or cur["orfas"]:
        print(f"\n[curadoria] {cur['aplicadas']} correções reaplicadas"
              + (f" | {cur['orfas']} órfãs" if cur["orfas"] else ""))
    if derivado and derivado["rejeitados"]:
        erros.extend({"passo": "tratar", **r} for r in derivado["rejeitados"])

    con = conexao.conectar()
    try:
        # O relatório lê `execucoes` ANTES do registro: a comparação é com a
        # rodada anterior de verdade, não com esta.
        passos.relatorio(con, resultados, derivado, saida["cinema"],
                         saida["instagram"], enriq, sumidos, duracao)
        execucoes.registrar_execucao(
            con, iniciada_em, round(duracao, 1), MODO, resultados,
            {"descrever": entradas["detalhes"]["res"],
             "precificar": entradas["tickets"]["res"],
             "derivado": derivado, "cinema": saida["cinema"],
             "instagram": saida["instagram"], "ruido": len(enriq["ruido"]),
             "dedupe_grupos": len(enriq["grupos"]),
             "sumidos": len(sumidos) if sumidos is not None else None},
            erros)
    finally:
        con.close()

    quebradas = [n for n in passos.ORDEM_FONTES
                 if (resultados[n] or {}).get("erro")]
    return dg.MaterializeResult(metadata={
        "duracao_s": round(duracao, 1), "modo": MODO,
        "erros": len(erros), "fontes_quebradas": ", ".join(quebradas) or "—",
        "coletados": sum(r.get("coletados") or 0
                         for r in resultados.values() if isinstance(r, dict))})


# --------------------------------------------------------------------------
# diagnóstico — a sonda da fatia 2, fora do job
# --------------------------------------------------------------------------

@dg.asset(key=["tratado", "contagem_eventos"], group_name="diagnostico",
          description="Sonda: conta `tratado.eventos` e mede o tempo de "
                      "abertura da conexão com o Neon. Só LÊ, não entra no "
                      "job da rodada, e serve para provar container e base "
                      "sem tocar em nada.")
def contagem_eventos(context: dg.AssetExecutionContext):
    agora = datetime.now(timezone.utc).isoformat()
    marca = time.perf_counter()
    con = conexao.conectar()
    conexao_s = time.perf_counter() - marca
    try:
        with con.cursor() as cur:
            total = cur.execute("SELECT count(*) AS n FROM tratado.eventos"
                                ).fetchone()["n"]
            futuros = cur.execute(
                "SELECT count(*) AS n FROM tratado.eventos "
                "WHERE start_date >= %s", (agora,)).fetchone()["n"]
            base = con.info.dbname
    finally:
        con.close()
    context.log.info(f"{base}: {total} eventos ({futuros} futuros), "
                     f"conexão em {conexao_s:.2f}s")
    return dg.MaterializeResult(metadata={
        "base": base, "eventos": total, "futuros": futuros,
        "conexao_s": round(conexao_s, 2)})


# --------------------------------------------------------------------------

ASSETS = [operacao_schema, *ASSETS_FONTE, cru_detalhes, cru_tickets,
          cru_cinema, cru_instagram, cru_extracao_flyer, operacao_midias,
          tratamento, cru_tmdb, operacao_posters, tratado_refresh,
          cru_podado, operacao_execucao, contagem_eventos]

# A rodada inteira, menos a sonda de diagnóstico (que só lê e não faz parte do
# pipeline). O teto de tempo é regra desta instância desde a fatia 0: run
# travado não se recupera sozinho, e sem teto ele segura o próximo.
rodada = dg.define_asset_job(
    "rodada_diaria",
    selection=dg.AssetSelection.all() - dg.AssetSelection.groups("diagnostico"),
    tags={"dagster/max_runtime": 7200})

# SEM schedule ainda (fatia 3 roda contra `eventos_teste`, só na mão). O
# schedule diário entra na fatia 4, junto com a base de produção.
defs = dg.Definitions(assets=ASSETS, jobs=[rodada])
