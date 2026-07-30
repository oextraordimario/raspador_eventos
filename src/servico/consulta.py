"""Camada de consulta da base unificada de eventos.

Contrato pensado para virar uma tool MCP: uma unica funcao parametrizada,
todos os argumentos opcionais, retorno em lista de dicts (JSON-serializavel).

Pegadinha das datas em formatos mistos (Sympla/Ingresse "+00:00", Shotgun
".000Z"): desde a Fase 0b quem resolve e o comum.upsert_eventos, que normaliza
tudo para ISO UTC na escrita (invariante do schema). Aqui basta normalizar os
PARAMETROS (tempo.norm_ts) — a comparacao no SQL volta a ser lexical, segura.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Também é entrypoint (`python src/servico/consulta.py` roda os exemplos), então
# põe src/ no sys.path. Quem já importou este módulo por pacote não paga nada.
_SRC = str(Path(__file__).resolve().parents[1])
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from base import conexao, tempo  # noqa: E402

# Campos uteis expostos ao agente (subconjunto enxuto da tabela).
# `id` (<fonte>:<id_nativo>) entrou em 2026-07-26: o site publico precisa de
# endereco proprio por evento (uma pagina por evento e o que a Fase 2 marca em
# JSON-LD) e a url da fonte nao serve de identificador de rota. Serve ao agente
# tambem — detalhar_evento aceita id ou url.
# preco_min = menor lote PAGO em R$ (total, com taxa); tem_gratis 1 = ha lote
# gratis nao esgotado (com preco_min NULL = evento gratis); esgotado 1 = sem
# ingressos; bairro/popularidade derivados da camada Bronze (specs camada-prata
# e lotes-ingressos).
# lat/lon entraram em 2026-07-28 (spec 20260728_rework-site §4.2): o link "ver
# no mapa" prefere coordenada ao endereco textual das fontes, que as vezes e
# sujo. Coordenada de local publico nao e dado pessoal — diferente do
# `organizador`, que a API do site continua ocultando.
# `slug` entrou em 2026-07-29 (spec 20260729_urls-semanticas): e o endereco do
# evento no site (/evento/<slug>), e vem no retorno para o front nunca calcular
# endereco — ele usa o que a base atribuiu. Tambem e o que permite a pagina
# saber que chegou por um endereco antigo e responder 308 para o canonico.
CAMPOS = ["id", "nome", "fonte", "start_date", "end_date", "cidade", "estado",
          "local_nome", "endereco", "bairro", "lat", "lon", "categoria",
          "organizador", "url", "imagem", "atracoes", "preco_min",
          "tem_gratis", "esgotado", "popularidade", "slug"]

# A descricao completa de dezenas de eventos e peso morto no contexto do agente;
# um trecho basta para ele entender o estilo do evento (o texto inteiro fica na
# base, indexado pelo FTS).
DESCRICAO_MAX = 300

# A hora exibida/filtrada e SEMPRE a de Brasilia; as colunas de tempo sao UTC
# (invariante do schema), entao quem converte e a query. Vale para os dois
# dominios: o horario da sessao de cinema e o dia do calendario de eventos.
_TZ_BSB = "America/Sao_Paulo"


def _con(con):
    """Conexão para UMA consulta: a recebida, ou uma nova que se fecha sozinha.

    Toda funcao daqui abria a propria conexao e a fechava. Funciona, mas cobra
    um handshake por CHAMADA — medido em 147 ms deste lado da rede, contra
    ~80 ms da query em si (2026-07-28). Rota que faz duas consultas — a de
    cinema ja faz: `buscar_filmes` + `facetas_filmes` — pagava o handshake
    duas vezes por render.

    Quem chama de fora (MCP, exemplos, testes) continua sem passar nada e nao
    muda; quem serve uma requisicao HTTP abre UMA conexao e a repassa.

    Returns:
        (conexao, fechar) — `fechar` diz se esta funcao e a dona dela.
    """
    return (con, False) if con is not None else (conexao.conectar(), True)


# Raio da Terra em km — a constante da haversine. PostGIS seria exagero para
# um recorte do tamanho do DF: a expressão direta erra centímetros aqui.
_RAIO_TERRA_KM = 6371


def buscar_eventos(texto=None, cidade=None, data_inicio=None, data_fim=None,
                   limite=20, incluir_ruido=False, bairro=None, tipo=None,
                   gratis=False, perto_lat=None, perto_lon=None, con=None):
    """Busca eventos na base unificada.

    Por padrao esconde o que o enriquecimento v1 marcou — eventos com ruido=1
    (anuncio/curso) e membros nao-canonicos de grupos de dedupe cross-fonte —
    e tambem eventos cancelados na origem (cancelado=1, derivado da Bronze) e
    sumidos do catalogo da fonte (sumido=1, provavel remocao silenciosa).
    Esgotado NAO some: "esta esgotado" e resposta util (campo `esgotado`).
    O canonico de um grupo carrega em `outras_urls` os links dos membros
    colapsados (o mesmo evento nas outras plataformas).

    Args:
        texto: busca textual sobre nome/categoria/atracoes/descricao. Sintaxe
            websearch do Postgres (ex.: "funk OR techno", frase entre aspas,
            -termo exclui). Omitido = sem filtro de texto.
        cidade: filtro exato por cidade.
        data_inicio: limite inferior (ISO) sobre start_date, inclusivo.
        data_fim: limite superior (ISO) sobre start_date, inclusivo.
        limite: numero maximo de resultados (ordenados por start_date).
        incluir_ruido: True devolve tambem os marcados como ruido, os
            cancelados e os sumidos (depuracao; nao exposto na tool MCP).
        bairro: um ou mais bairros/regioes (CSV ou lista, texto exato como
            aparece em facetas_eventos; ex.: "Asa Sul,Sudoeste"). Evento sem
            bairro conhecido fica de fora — e o unico filtro daqui que
            esconde por ausencia de dado, e por isso nunca e default.
        tipo: 'festa' ou 'show'. **Traz tambem os SEM ROTULO** (tipo IS NULL):
            a classificacao e heuristica, e esconder o que ela nao soube
            classificar transformaria uma duvida do sistema em ausencia na
            tela. Ver enriquecer._classificar_tipo.
        perto_lat/perto_lon: coordenada de quem esta perguntando. NAO filtra —
            ORDENA por distancia DENTRO de cada dia, e acrescenta
            `distancia_km` ao retorno. Nao filtra de proposito: raio esconde
            evento, e ~30% da agenda (Ticket and Go e Instagram) nao tem
            coordenada nenhuma — esses vao para o fim do dia, nunca somem. O
            dia continua mandando na ordem porque a pagina e uma AGENDA: a
            pergunta real e "o que tem hoje perto de mim", nao "o mais perto
            de todos, em qualquer data".
        gratis: True devolve so eventos com lote gratis nao esgotado. Estava
            na api/dados.py como filtro de lista ate 2026-07-28 — o que, por
            rodar DEPOIS do `limite`, filtrava os N ja buscados em vez da
            base ("so gratis" com limite 60 devolvia os gratis que coubessem
            nos 60 primeiros, nao os 60 primeiros gratis).

    Returns:
        Lista de dicts (nunca sqlite3.Row), ordenada por start_date.
    """
    con, meu = _con(con)

    where, params = [], []
    if not incluir_ruido:
        where.append("e.ruido = 0")
        where.append("(e.cancelado IS NULL OR e.cancelado = 0)")
        where.append("e.sumido = 0")
    # Duplicata cross-fonte: so o canonico responde pelo grupo.
    where.append("e.dedupe_canonico = 1")
    if texto:
        where.append("e.busca @@ websearch_to_tsquery('pt', %s)")
        params.append(texto)
    if cidade:
        where.append("e.cidade = %s")
        params.append(cidade)
    # Parametro de data normalizado como a coluna (invariante do schema);
    # valor que nao parseia vira NULL e a comparacao nao devolve nada.
    if data_inicio:
        where.append("e.start_date >= %s")
        params.append(tempo.norm_ts(data_inicio))
    if data_fim:
        where.append("e.start_date <= %s")
        params.append(tempo.norm_ts(data_fim))
    bairros = _lista(bairro)
    if bairros:
        where.append("e.bairro = ANY(%s)")
        params.append(bairros)
    if tipo:
        # o sem-rotulo nunca some: ver a docstring
        where.append("(e.tipo = %s OR e.tipo IS NULL)")
        params.append(tipo)
    if gratis:
        where.append("e.tem_gratis = 1")

    # outras_urls: links do mesmo evento nas outras plataformas (NULL sem grupo).
    outras = ("(SELECT string_agg(o.url, ',') FROM public.eventos o "
              "WHERE o.dedupe_grupo = e.dedupe_grupo AND o.id != e.id) "
              "AS outras_urls")
    descr = f"substr(e.descricao, 1, {DESCRICAO_MAX}) AS descricao"

    # "Perto de mim" (NI-46): haversine direto em SQL. A coordenada de quem
    # pergunta desce como parametro, e nao e gravada nem logada em lugar
    # nenhum — nem aqui, nem no analytics (ver a nota do `?perto=` na API).
    perto = perto_lat is not None and perto_lon is not None
    if perto:
        # O CASE não é defensivo à toa: `least(1, NULL)` no Postgres devolve 1
        # (ele IGNORA nulos, diferente de quase todo operador), e sem ele todo
        # evento sem coordenada — 30% da agenda — sairia com acos(1) = 0, ou
        # seja, "0,0 km": exatamente onde a pessoa está. Mentira com cara de
        # precisão, que é o pior modo de falha deste recurso.
        dist = (f"CASE WHEN e.lat IS NULL OR e.lon IS NULL THEN NULL ELSE "
                f"round(({_RAIO_TERRA_KM} * acos(least(1, "
                "cos(radians(%s)) * cos(radians(e.lat)) * "
                "cos(radians(e.lon) - radians(%s)) + "
                "sin(radians(%s)) * sin(radians(e.lat)))))::numeric, 1) END")
        extra = f", {dist} AS distancia_km"
        # os parametros da distancia vem ANTES dos do WHERE: no SELECT
        params = [perto_lat, perto_lon, perto_lat] + params
    else:
        extra = ""

    sql = (f"SELECT {', '.join(CAMPOS)}, {descr}, {outras}{extra} "
           "FROM public.eventos e")
    if where:
        sql += " WHERE " + " AND ".join(where)
    if perto:
        # dia LOCAL primeiro (a lista é agrupada por dia na tela), distância
        # depois; quem não tem coordenada vai para o fim DO DIA, não some
        dia_local = ("to_char(e.start_date::timestamptz AT TIME ZONE "
                     f"'{_TZ_BSB}', 'YYYY-MM-DD')")
        sql += (f" ORDER BY {dia_local}, (e.lat IS NULL), "
                "distancia_km NULLS LAST, e.start_date")
    else:
        sql += " ORDER BY e.start_date"
    sql += " LIMIT %s"
    params.append(limite)

    rows = con.execute(sql, params).fetchall()
    if meu:
        con.close()
    return [dict(r) for r in rows]


# Os mesmos filtros que a busca aplica por padrao. Ficam numa constante porque
# a faceta TEM que enxergar exatamente o que a lista enxerga: dia habilitado no
# calendario que devolve zero resultado e pior que dia desabilitado.
_VISIVEL = ("ruido = 0 AND (cancelado IS NULL OR cancelado = 0) "
            "AND sumido = 0 AND dedupe_canonico = 1")


def facetas_eventos(cidade=None, con=None):
    """Valores dos filtros da pagina de festas, so sobre evento FUTURO visivel.

    O analogo do facetas_filmes (NI-35) para eventos. Hoje devolve os dias com
    evento, que e o que o calendario habilita.

    **O dia e o dia LOCAL SIMPLES** (00:00–24:00 de Brasilia), e nao o dia da
    vida noturna com corte as 6h que os atalhos de periodo usam. Nao e
    inconsistencia: a lista agrupa por dia local simples (`chaveDia` do front),
    entao uma festa de sabado 1h aparece sob "sabado" na tela — e o dia
    "sabado" do calendario precisa traze-la. O corte das 6h continua valendo
    onde sempre valeu: nos atalhos hoje/fds/7d e nos rotulos "hoje"/"amanha".

    Returns:
        {"dias": [...], "bairros": [...], "tipos": {...}} — ordenados, so o
        que tem evento. Bairro nulo NAO vira faceta: a opcao existe quando ha
        o que filtrar.

        `tipos` sao CONTAGENS ({"festa": n, "show": n, "sem_rotulo": n}), e
        nao uma lista de opcoes, de proposito: quem consome decide se o filtro
        vale a pena com base na cobertura. Hoje a heuristica classifica ~1/4
        da agenda (o sinal de `categoria` sumiu quando as constantes de
        Shotgun e Ticket and Go sairam, e o Sympla so diz "musica"), e um
        filtro que devolve quase tudo e pior que filtro nenhum — ele promete
        um recorte que nao faz. Quando o NI-05 (LLM) assumir a coluna, a
        cobertura sobe e o filtro se acende sozinho, sem mudar codigo.
    """
    con, meu = _con(con)
    agora = datetime.now(timezone.utc).isoformat()
    where = [f"({_VISIVEL})", "start_date >= %s"]
    params = [agora]
    if cidade:
        where.append("cidade = %s")
        params.append(cidade)
    onde = " AND ".join(where)
    dias = [r["dia"] for r in con.execute(
        "SELECT DISTINCT to_char(start_date::timestamptz AT TIME ZONE "
        f"'{_TZ_BSB}', 'YYYY-MM-DD') AS dia FROM public.eventos "
        f"WHERE {onde} ORDER BY dia", params)]
    # ordenado por QUANTIDADE, não por alfabeto: numa lista de vinte regiões,
    # a que tem quinze festas precisa estar no topo, não em "Á"
    bairros = [r["bairro"] for r in con.execute(
        "SELECT bairro, count(*) AS n FROM public.eventos "
        f"WHERE {onde} AND bairro IS NOT NULL "
        "GROUP BY bairro ORDER BY n DESC, bairro", params)]
    tipos = {"festa": 0, "show": 0, "sem_rotulo": 0}
    for r in con.execute(
            "SELECT coalesce(tipo, 'sem_rotulo') AS t, count(*) AS n "
            f"FROM public.eventos WHERE {onde} GROUP BY 1", params):
        tipos[r["t"]] = r["n"]
    if meu:
        con.close()
    return {"dias": dias, "bairros": bairros, "tipos": tipos}


def _por_slug_antigo(con, entidade, slug, campos="id, dedupe_grupo, dedupe_canonico"):
    """O CAMINHO TRISTE do endereço: slug que não existe mais na prata.

    2,3% dos eventos trocam de nome durante a vida (medido no cru), e trocar de
    nome troca o slug — o link que alguém mandou no WhatsApp morreria. A view
    `public.slugs_antigos` guarda todo endereço já atribuído e só devolve os que
    ainda têm registro, então quem chega por um slug velho é atendido e a página
    responde 308 para o endereço de hoje (a comparação `ev.slug != parâmetro`).

    Roda SÓ depois de a busca normal falhar: uma consulta a mais no 404, nenhuma
    no caminho feliz.
    """
    tabela = "public.eventos" if entidade == "eventos" else "public.filmes"
    return con.execute(
        f"SELECT {campos} FROM {tabela} t "
        "JOIN public.slugs_antigos h ON h.registro_id = t.id "
        "WHERE h.entidade = %s AND h.slug = %s", (entidade, slug)).fetchone()


def detalhar_evento(url, con=None):
    """Devolve UM evento completo: os mesmos campos da busca, a descricao
    INTEIRA (sem o corte de DESCRICAO_MAX) e a lista de lotes de ingresso com
    o nome cru da fonte (a condicao do lote — "CORTESIA FEMININA ATE 00H",
    "meia-entrada" — esta no nome, de proposito; spec 20260710_lotes-ingressos).

    Lookup pela url exata que buscar_eventos devolveu (em url ou outras_urls).
    Se a url for de um membro nao-canonico de grupo de dedupe, responde o
    canonico. Nao achou -> {"erro": ...}.

    O argumento e um IDENTIFICADOR, e o formato dele decide a coluna. Sao tres,
    e nenhum se confunde com os outros:

        comeca com "http"  -> `url`   (a tool MCP passa a url da fonte)
        contem ":" ou "~"  -> `id`    (`<fonte>:<id_nativo>`; o `~` e a grafia
                                       do MESMO id na rota antiga do site —
                                       `/evento/sympla~3520331` —, porque `:`
                                       nao vive bem numa URL)
        senao              -> `slug`  (`forro-na-varanda-26-07`, o endereco
                                       publico desde 2026-07-29)

    O `~` continua atendido de proposito, e nao por descuido: e o endereco que
    esteve no ar e no sitemap, e quem chega por ele recebe 308 para o slug (o
    front compara `ev.slug` com o parametro da rota). Nenhum id de fonte contem
    `~`, entao a troca e sem ambiguidade.

    O nome do parametro segue `url` por compatibilidade: e o contrato que o MCP
    ja usa, e renomear a chave da API do site quebraria o cliente por nada.
    """
    con, meu = _con(con)
    alvo = (url or "").strip()
    if not alvo.startswith("http") and "~" in alvo:
        alvo = alvo.replace("~", ":")
    coluna = ("url" if alvo.startswith("http")
              else "id" if ":" in alvo else "slug")
    row = con.execute(f"SELECT id, dedupe_grupo, dedupe_canonico FROM public.eventos "
                      f"WHERE {coluna} = %s", (alvo,)).fetchone()
    if not row and coluna == "slug":
        row = _por_slug_antigo(con, "eventos", alvo)
    if row and not row["dedupe_canonico"] and row["dedupe_grupo"]:
        row = con.execute(
            "SELECT id FROM public.eventos WHERE dedupe_grupo = %s "
            "AND dedupe_canonico = 1", (row["dedupe_grupo"],)).fetchone() or row
    if not row:
        if meu:
            con.close()
        return {"erro": f"nenhum evento na base com a url {url!r} — use a url "
                        "exata devolvida por buscar_eventos"}
    outras = ("(SELECT string_agg(o.url, ',') FROM public.eventos o "
              "WHERE o.dedupe_grupo = e.dedupe_grupo AND o.id != e.id) "
              "AS outras_urls")
    ev = dict(con.execute(
        f"SELECT {', '.join(CAMPOS)}, e.descricao, {outras} "
        "FROM public.eventos e WHERE e.id = %s", (row["id"],)).fetchone())
    ev["lotes"] = [dict(r) for r in con.execute(
        "SELECT nome, preco, taxa, gratis, esgotado FROM public.lotes "
        "WHERE evento_id = %s ORDER BY ordem", (row["id"],))]
    if meu:
        con.close()
    return ev


# ── Domínio cinema (NI-07, spec 20260711_raspagem-cinema) ──────────────────

# Campos de filmes expostos ao agente. `poster` entrou na lista com o rework
# da página de cinema (NI-35 — o card do site precisa dele) e sinopse/ano/
# nota/votos com o NI-36 (TMDB); poster_proprio é a cópia no storage (NI-37,
# o front prefere quando existe); tmdb_id permite linkar a página do filme no
# TMDB (atribuição exigida pelos ToS deles). `trailer` segue só no
# sessoes_filme.
CAMPOS_FILME = ["id", "titulo", "titulo_original", "generos", "duracao_min",
                "classificacao", "distribuidora", "url", "poster",
                "poster_proprio", "em_pre_venda", "sinopse", "ano", "nota",
                "votos", "tmdb_id", "slug"]

# Forma de um slug nosso: so [a-z0-9-]. Serve de GUARDA antes de qualquer
# interpolacao em LIKE/regex — ver sessoes_filme.
_E_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _lista(v):
    """Normaliza um filtro múltiplo: None/''→[], 'a,b'→['a','b'], lista→lista.

    Aceitar CSV além de lista deixa a api/dados.py repassar a querystring
    sem parse próprio (a regra de "sem lógica na API" vale até para vírgula).
    """
    if not v:
        return []
    if isinstance(v, str):
        v = v.split(",")
    return [s.strip() for s in v if s and s.strip()]


def _filtro_hora(where, params, hora_de, hora_ate, col="s.inicio"):
    """Janela de HORA LOCAL de Brasília sobre uma coluna UTC (`ate` exclusivo);
    de > ate vira janela que cruza a meia-noite. Compartilhado por
    buscar_filmes e sessoes_filme — a regra tem que ser uma só."""
    hora_sql = f"EXTRACT(HOUR FROM ({col}::timestamptz AT TIME ZONE '{_TZ_BSB}'))"
    if hora_de is not None and hora_ate is not None and hora_de > hora_ate:
        where.append(f"({hora_sql} >= %s OR {hora_sql} < %s)")
        params.extend([hora_de, hora_ate])
    else:
        if hora_de is not None:
            where.append(f"{hora_sql} >= %s")
            params.append(hora_de)
        if hora_ate is not None:
            where.append(f"{hora_sql} < %s")
            params.append(hora_ate)


def _filtro_cinemas(where, params, cinema, col="s.cinema"):
    """Um ou mais cinemas (parcial, sem caixa), OR entre eles."""
    cinemas = _lista(cinema)
    if cinemas:
        where.append("(" + " OR ".join([f"{col} ILIKE %s"] * len(cinemas)) + ")")
        params.extend(f"%{c}%" for c in cinemas)


# Como se ouve o filme. A fonte não tem campo próprio para isso: manda tudo
# junto em `tipos`, componentes separados por "/" ("3D/XD/Dublado",
# "Vip/Legendado"). Casar por substring é seguro porque nenhum OUTRO
# componente carrega essas palavras — os demais são formato (3D), sala (XD,
# Vip, D-Box) ou sessão temática (Cine Inclusivo, Sessão Azul).
AUDIOS = ("Dublado", "Legendado", "Nacional")


def _audios(v):
    """Só os valores conhecidos, na ordem de AUDIOS. Filtro vem da
    querystring, que é entrada de estranho: o que não é áudio some aqui, em
    vez de virar um ILIKE que não casa com nada e devolve tela vazia."""
    pedidos = {a.strip().lower() for a in _lista(v)}
    return [a for a in AUDIOS if a.lower() in pedidos]


def _filtro_audio(where, params, audio, col="s.tipos"):
    """Um ou mais áudios (dublado/legendado/nacional), OR entre eles."""
    escolhidos = _audios(audio)
    if escolhidos:
        where.append("(" + " OR ".join([f"{col} ILIKE %s"] * len(escolhidos)) + ")")
        params.extend(f"%{a}%" for a in escolhidos)


def _audios_de(tipos):
    """Quais áudios aparecem numa coleção de `tipos` crus — é o que vira as
    OPÇÕES do filtro (só existe no drop o que tem sessão)."""
    vistos = " | ".join(t or "" for t in tipos).lower()
    return [a for a in AUDIOS if a.lower() in vistos]


def buscar_filmes(texto=None, data_inicio=None, data_fim=None, cinema=None,
                  generos=None, classificacao=None, hora_de=None,
                  hora_ate=None, audio=None, limite=20, con=None):
    """Filmes em cartaz nos cinemas-alvo de Brasília, agregados por filme.

    Sessões passadas não contam: sem data_inicio, a janela começa AGORA.
    Ordena por nº de sessões na janela (mais em cartaz primeiro) — o agente
    reordena como quiser.

    Args:
        texto: busca textual sobre título e gêneros (websearch, ex.:
            "animação", "terror OR suspense"). Omitido = todos em cartaz.
        data_inicio: limite inferior (ISO) sobre o início da sessão; default agora.
        data_fim: limite superior (ISO), inclusivo.
        cinema: um ou mais cinemas (string parcial sem caixa, CSV ou lista:
            "pier", "kinoplex", "Cine Brasília,Cine Cultura" — OR entre eles).
        generos: um ou mais gêneros (CSV ou lista; casa por substring no CSV
            da fonte, OR entre eles: "Terror,Suspense").
        classificacao: uma ou mais classificações indicativas, texto EXATO da
            fonte ("Livre", "6 anos" — os valores estão em facetas_filmes()).
        hora_de/hora_ate: janela da HORA LOCAL de Brasília do início da sessão
            (ints 0–23; `ate` exclusivo). hora_de > hora_ate vira janela que
            cruza a meia-noite (ex.: 22→6 = sessão coruja).
        audio: como se ouve o filme, um ou mais de "Dublado", "Legendado",
            "Nacional" (CSV ou lista, OR entre eles). Valor fora dessa lista
            é ignorado.
        limite: máximo de filmes.

    Returns:
        Lista de dicts: campos do filme + sessoes (contagem na janela),
        cinemas (nomes, ordenados), audios (quais das sessões da janela são
        dubladas/legendadas/nacionais) e primeira_sessao/ultima_sessao
        (ISO UTC).
    """
    con, meu = _con(con)
    where = ["s.inicio >= %s"]
    params = [tempo.norm_ts(data_inicio)
              or datetime.now(timezone.utc).isoformat()]
    if data_fim:
        where.append("s.inicio <= %s")
        params.append(tempo.norm_ts(data_fim))
    if texto:
        where.append("f.busca @@ websearch_to_tsquery('pt', %s)")
        params.append(texto)
    _filtro_cinemas(where, params, cinema)
    gens = _lista(generos)
    if gens:
        where.append("(" + " OR ".join(["f.generos ILIKE %s"] * len(gens)) + ")")
        params.extend(f"%{g}%" for g in gens)
    classes = _lista(classificacao)
    if classes:
        where.append("f.classificacao = ANY(%s)")
        params.append(classes)
    _filtro_hora(where, params, hora_de, hora_ate)
    _filtro_audio(where, params, audio)
    campos = ", ".join(f"f.{c}" for c in CAMPOS_FILME)
    rows = con.execute(
        f"SELECT {campos}, COUNT(s.id) AS sessoes, "
        "string_agg(DISTINCT s.cinema, ', ' ORDER BY s.cinema) AS cinemas, "
        "string_agg(DISTINCT s.tipos, '|') AS tipos_agg, "
        "MIN(s.inicio) AS primeira_sessao, MAX(s.inicio) AS ultima_sessao "
        "FROM public.filmes f JOIN public.sessoes s ON s.filme_id = f.id "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY {campos} ORDER BY COUNT(s.id) DESC, f.titulo LIMIT %s",
        [*params, limite]).fetchall()
    if meu:
        con.close()
    filmes = []
    for r in rows:
        d = dict(r)
        # o `tipos` cru não sai daqui: quem consome a lista quer saber se dá
        # para ver o filme dublado, não que exista uma sessão "3D/D-Box/Dublado"
        d["audios"] = _audios_de([d.pop("tipos_agg")])
        filmes.append(d)
    return filmes


def facetas_filmes(con=None):
    """Valores distintos dos filtros da página de cinema (NI-35), calculados
    só sobre o que tem sessão FUTURA — faceta de filme que saiu de cartaz é
    opção que devolve vazio.

    Returns:
        {"generos": [...], "classificacoes": [...], "cinemas": [...],
        "audios": [...], "dias": [...]} — gêneros desmembrados do CSV da
        fonte, classificações no texto exato (ordenadas Livre→18), cinemas
        pelos apelidos canônicos, áudios (dublado/legendado/nacional) que
        têm sessão, e os dias LOCAIS com sessão futura.
    """
    con, meu = _con(con)
    agora = datetime.now(timezone.utc).isoformat()
    rows = con.execute(
        "SELECT DISTINCT f.generos, f.classificacao "
        "FROM public.filmes f JOIN public.sessoes s ON s.filme_id = f.id "
        "WHERE s.inicio >= %s", (agora,)).fetchall()
    generos, classes = set(), set()
    for r in rows:
        generos.update(g.strip() for g in (r["generos"] or "").split(",")
                       if g.strip())
        if r["classificacao"]:
            classes.add(r["classificacao"])
    cinemas = [r["cinema"] for r in con.execute(
        "SELECT DISTINCT cinema FROM public.sessoes WHERE inicio >= %s "
        "ORDER BY cinema", (agora,))]
    audios = _audios_de(r["tipos"] for r in con.execute(
        "SELECT DISTINCT tipos FROM public.sessoes WHERE inicio >= %s",
        (agora,)))
    # dias LOCAIS com sessão futura — é o que o calendário do site habilita
    # (a grade real cobre ~8 dias; o resto do mês fica desabilitado)
    dias = [r["dia"] for r in con.execute(
        "SELECT DISTINCT to_char(inicio::timestamptz AT TIME ZONE "
        f"'{_TZ_BSB}', 'YYYY-MM-DD') AS dia "
        "FROM public.sessoes WHERE inicio >= %s ORDER BY dia", (agora,))]
    if meu:
        con.close()

    def _ordem_classe(c):
        # "Livre" antes de tudo; o resto pelo número ("6 anos", "12 anos"...)
        digitos = "".join(ch for ch in c if ch.isdigit())
        return (0, 0) if not digitos else (1, int(digitos))
    return {"generos": sorted(generos),
            "classificacoes": sorted(classes, key=_ordem_classe),
            "cinemas": cinemas, "audios": audios, "dias": dias}


def sessoes_filme(filme, data_inicio=None, data_fim=None, cinema=None,
                  hora_de=None, hora_ate=None, audio=None, con=None):
    """Sessões detalhadas de UM filme (horário, cinema, sala, tipos, preço,
    link de compra) — o análogo do detalhar_evento para o cinema.

    `filme` é o slug (`homem-aranha-um-novo-dia-2026`), o id ou o título (busca
    parcial, sem caixa/acento via ILIKE + unaccent); com mais de um candidato,
    responde o com mais sessões futuras.
    Mesma janela default da busca: sessões passadas ficam de fora.
    `cinema` (parcial, CSV/lista), `hora_de`/`hora_ate` (hora LOCAL, `ate`
    exclusivo) e `audio` (Dublado/Legendado/Nacional) filtram as sessões —
    mesmos filtros da busca, para achar o lugar, a hora e a versão certa de
    ver ESTE filme. `cinemas` e `audios` no retorno listam onde e como o
    filme passa SEM os filtros aplicados (são as opções do filtro, não o
    resultado dele).
    """
    con, meu = _con(con)
    alvo = (filme or "").strip()
    agora = datetime.now(timezone.utc).isoformat()
    row = con.execute("SELECT id FROM public.filmes WHERE slug = %s OR id = %s",
                      (alvo, alvo)).fetchone()
    if not row and _E_SLUG.match(alvo):
        # Slug curto: o `ano` vem do TMDB e pode chegar uma rodada depois do
        # filme, então um link compartilhado nesse intervalo aponta para
        # `/cinema/mil-luas` enquanto o endereço de hoje é `/cinema/mil-luas-2026`.
        # Só resolve quando o prefixo identifica UM filme — com dois candidatos
        # não há o que adivinhar, e cai no casamento por título abaixo.
        #
        # A guarda `_E_SLUG` é o que torna a interpolação segura: sem ela, `_` e
        # `%` do parâmetro seriam curinga do LIKE e os metacaracteres iriam para
        # dentro da regex. Rota é entrada de estranho.
        candidatos = con.execute(
            "SELECT id FROM public.filmes WHERE slug ~ %s",
            (f"^{alvo}-[0-9]{{4}}$",)).fetchall()
        row = candidatos[0] if len(candidatos) == 1 else None
    if not row and _E_SLUG.match(alvo):
        # endereço de antes de um renome (ver _por_slug_antigo)
        row = _por_slug_antigo(con, "filmes", alvo, campos="id")
    if not row and alvo:
        # título parcial, sem caixa/acento; empate vai para quem tem mais
        # sessões futuras (o "em cartaz de verdade")
        row = con.execute(
            "SELECT f.id FROM public.filmes f "
            "LEFT JOIN public.sessoes s ON s.filme_id = f.id AND s.inicio >= %s "
            "WHERE unaccent(f.titulo) ILIKE unaccent(%s) "
            "GROUP BY f.id ORDER BY COUNT(s.id) DESC LIMIT 1",
            (agora, f"%{alvo}%")).fetchone()
    if not row:
        if meu:
            con.close()
        return {"erro": f"nenhum filme em cartaz casando com {filme!r} — use "
                        "o id ou título devolvido por buscar_filmes"}
    campos = ", ".join(CAMPOS_FILME + ["trailer"])
    f = dict(con.execute(f"SELECT {campos} FROM public.filmes WHERE id = %s",
                         (row["id"],)).fetchone())
    inicio_janela = tempo.norm_ts(data_inicio) or agora
    f["cinemas"] = [r["cinema"] for r in con.execute(
        "SELECT DISTINCT cinema FROM public.sessoes "
        "WHERE filme_id = %s AND inicio >= %s ORDER BY cinema",
        (row["id"], inicio_janela))]
    f["audios"] = _audios_de(r["tipos"] for r in con.execute(
        "SELECT DISTINCT tipos FROM public.sessoes "
        "WHERE filme_id = %s AND inicio >= %s", (row["id"], inicio_janela)))
    where = ["filme_id = %s", "inicio >= %s"]
    params = [row["id"], inicio_janela]
    if data_fim:
        where.append("inicio <= %s")
        params.append(tempo.norm_ts(data_fim))
    _filtro_cinemas(where, params, cinema, col="cinema")
    _filtro_hora(where, params, hora_de, hora_ate, col="inicio")
    _filtro_audio(where, params, audio, col="tipos")
    f["sessoes"] = [dict(r) for r in con.execute(
        "SELECT cinema, inicio, sala, tipos, preco, url_compra FROM public.sessoes "
        f"WHERE {' AND '.join(where)} ORDER BY inicio, cinema", params)]
    if meu:
        con.close()
    return f


def procedencia(con=None):
    """Quando cada fonte foi coletada pela última vez, e quanto ela responde
    hoje na base.

    Existe porque o site precisa mostrar a idade do dado (spec
    20260726_abrir-ao-publico §3 passo 3): enquanto a raspagem não for
    comprovadamente diária, esconder que o dado é de três dias atrás é o pior
    modo de falha do produto — resposta errada com cara de certa.

    `raspado_em` é a âncora certa: só o upsert do catálogo o atualiza (os
    passos descrever/precificar mexem em outras colunas), então ele responde
    "quando esta fonte foi vista viva pela última vez".

    Returns:
        Lista de dicts {fonte, ultima_coleta (ISO UTC), eventos, futuros},
        da fonte mais recente para a mais velha.
    """
    con, meu = _con(con)
    agora = datetime.now(timezone.utc).isoformat()
    rows = con.execute(
        "SELECT fonte, MAX(raspado_em) AS ultima_coleta, "
        "       COUNT(*) AS eventos, "
        "       COUNT(*) FILTER (WHERE start_date >= %s AND ruido = 0 "
        "                        AND sumido = 0 "
        "                        AND (cancelado IS NULL OR cancelado = 0)) "
        "         AS futuros "
        "FROM public.eventos GROUP BY fonte ORDER BY MAX(raspado_em) DESC",
        (agora,)).fetchall()
    if meu:
        con.close()
    return [dict(r) for r in rows]


def _mostrar(titulo, eventos):
    print(f"\n### {titulo}  ({len(eventos)} resultados)")
    if not eventos:
        print("  (nenhum)")
        return
    for e in eventos:
        quando = (e["start_date"] or "")[:16].replace("T", " ")
        print(f"  - {quando} | [{e['fonte']}] {(e['nome'] or '')[:55]}")
        print(f"      {e['local_nome'] or '?'} - {e['cidade'] or '?'} | {e['url']}")


if __name__ == "__main__":
    agora = datetime.now(timezone.utc).isoformat()

    # 1) "pagode" em Brasilia, a partir de agora.
    _mostrar('"pagode" em Brasilia (futuros)',
             buscar_eventos(texto="pagode", cidade="Brasília",
                            data_inicio=agora))

    # 2) proximos eventos sem filtro de texto -- checa as 3 fontes e que nada
    #    passado vaza.
    proximos = buscar_eventos(cidade="Brasília", data_inicio=agora, limite=50)
    _mostrar("Proximos eventos (sem texto, so futuros)", proximos[:8])
    fontes = sorted({e["fonte"] for e in proximos})
    passados = [e for e in proximos
                if tempo.norm_ts(e["start_date"])
                and tempo.norm_ts(e["start_date"]) < agora]
    print(f"    fontes presentes: {fontes} | eventos passados que vazaram: {len(passados)}")

    # 3) um genero (funk OR techno).
    _mostrar('"funk OR techno" (futuros)',
             buscar_eventos(texto="funk OR techno", cidade="Brasília",
                            data_inicio=agora))

    # 4) caso que deve retornar vazio.
    _mostrar("Texto sem correspondencia (deve vir vazio)",
             buscar_eventos(texto="xyzzyabracadabra123"))
