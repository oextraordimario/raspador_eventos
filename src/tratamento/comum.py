"""O motor comum das trilhas de tratamento — escrita na camada TRATADO.

Cada `tratamento/<fonte>.py` declara só o que é DA SUA FONTE (`normalizar`,
`DERIVACOES`, `LOTES`, `CONFERIR`); o upsert, a agregação e o laço que percorre
o `cru` moram aqui. Sem isso o esqueleto duplicaria cinco vezes e as cópias
divergiriam por descuido — que é o risco real de separar por fonte.

**A prata se reconstrói do cru** (fatia 7, 2026-07-28). Até então a coleta
escrevia direto em `tratado.eventos` — o `_normalizar` de cada scraper produzia
a linha pronta, e não existia uma linha de código que lesse o bruto e produzisse
o evento. Era o NI-55: não dava para olhar o cru e dizer o que a prata deveria
conter. Hoje `aplicar()` apaga nada e reescreve TODAS as colunas de conteúdo a
partir do bruto, então `--so-derivar` reproduz a base inteira.

O que este módulo NÃO toca, de propósito: `sumido` (deriva de
`operacao.coletas`, em `tratamento/sumido.py`), `ruido`/`dedupe_*` (do
`enriquecer`) e `busca` (do `busca`). São camadas posteriores do mesmo estágio,
cada uma dona das suas colunas.
"""

import json

from base import tempo
from tratamento import ingresse, shotgun, sympla, ticketandgo, zig

# fonte -> módulo de tratamento. Uma trilha por fonte (spec D6):
#   coleta/<fonte>.py -> cru.<fonte> -> tratamento/<fonte>.py -> tratado.eventos
TRILHAS = {"sympla": sympla, "ingresse": ingresse, "zig": zig,
           "shotgun": shotgun, "ticketandgo": ticketandgo}

# Todas as colunas de conteúdo de tratado.eventos: as de IDENTIDADE (vêm do
# payload de catálogo, via normalizar) e as DERIVADAS (vêm das outras origens e
# da agregação de lotes). O upsert escreve a lista inteira sempre — coluna que
# nenhuma origem produziu vira NULL, e é isso que torna a reconstrução fiel:
# não há resíduo de rodada anterior sobrevivendo por COALESCE.
COLS_EVENTO = ["id", "fonte", "id_nativo", "nome", "start_date", "end_date",
               "cidade", "estado", "local_nome", "endereco", "lat", "lon",
               "categoria", "organizador", "url", "imagem", "raspado_em",
               "descricao", "atracoes", "preco_min",
               "bairro", "popularidade", "esgotado", "cancelado", "tem_gratis"]

# Colunas de data com invariante de schema (ISO UTC "+00:00", via
# tempo.norm_ts) — é o que torna a comparação lexical no SQL segura.
_COLS_DATA = {"start_date", "end_date", "raspado_em"}


def upsert_eventos(con, eventos):
    """Grava uma lista de eventos já normalizados (dicts) em tratado.eventos.

    Escrita PURA na prata: não toca `cru` nem `operacao`. Até 2026-07-28 esta
    função também gravava o payload bruto — a coleta a chamava e ganhava a
    escrita da bronze de brinde, que era a violação de camada do NI-55.

    As colunas de data passam por tempo.norm_ts aqui: é o único ponto de
    escrita, então é ele que garante o invariante do schema.

    Não há COALESCE: toda coluna de COLS_EVENTO é reescrita com o valor novo.
    Preservar valor antigo por COALESCE só faz sentido quando a escrita é
    parcial — e não é mais.
    """
    placeholders = ",".join("%s" for _ in COLS_EVENTO)
    # O nome sem schema (`eventos.`) é como o Postgres expõe a tabela-alvo
    # dentro do ON CONFLICT DO UPDATE, mesmo com o INSERT qualificado.
    updates = ",".join(f"{c}=excluded.{c}" for c in COLS_EVENTO if c != "id")
    sql = (f"INSERT INTO tratado.eventos ({','.join(COLS_EVENTO)}) "
           f"VALUES ({placeholders}) "
           f"ON CONFLICT(id) DO UPDATE SET {updates}")
    con.cursor().executemany(sql, [
        [tempo.norm_ts(e.get(c)) if c in _COLS_DATA else e.get(c)
         for c in COLS_EVENTO]
        for e in eventos])
    return len(eventos)


def agregar(lotes):
    """Colunas de eventos que resumem os lotes. Leitura combinada:
    preco_min=38.99 + tem_gratis=1 -> "grátis em condições, pagos a partir de
    R$ 38,99"; preco_min NULL + tem_gratis=1 -> evento grátis."""
    pagos = [lt["preco"] for lt in lotes
             if not lt["gratis"] and lt["preco"] is not None]
    return {"preco_min": min(pagos) if pagos else None,
            "tem_gratis": 1 if any(lt["gratis"] and lt["esgotado"] != 1
                                   for lt in lotes) else 0,
            "esgotado": 1 if all(lt["esgotado"] == 1 for lt in lotes) else 0}


def ler_cru(con, fonte):
    """Estado corrente de uma fonte no cru, agrupado por evento.

    Lê a view `_atual` (a versão mais recente de cada id_nativo+origem), não a
    tabela: quem quiser série temporal vai na tabela.

    Devolve [(id_nativo, linha_do_catalogo, {origem: payload})]. Evento sem
    payload de catálogo fica FORA: não há de onde tirar nome, data e URL, e
    inventá-los a partir de um payload de tickets seria adivinhação.
    """
    por_evento = {}
    for r in con.execute(
            f"SELECT * FROM cru.{fonte}_atual ORDER BY id_nativo, origem"):
        d = por_evento.setdefault(r["id_nativo"], {"cru": None, "origens": {}})
        d["origens"][r["origem"]] = json.loads(r["payload"])
        if r["origem"] == "catalogo":
            d["cru"] = r
    return [(k, v["cru"], v["origens"]) for k, v in por_evento.items()
            if v["cru"] is not None]


def _tratar(fonte, modulo, id_nativo, cru, origens):
    """Um evento: payloads do cru → (campos de tratado.eventos, lotes).

    Devolve (None, motivo) quando a guarda reprova. A guarda é a do §6.3, e
    existe porque cada troca de API deixa duas eras de payload sob a mesma
    origem: o parser novo aplicado ao payload velho NÃO falha — acha campos
    homônimos por coincidência e degrada em silêncio. Payload que não passa é
    PULADO (o dado bom da rodada anterior fica), nunca sobrescreve.
    """
    base = modulo.normalizar(origens["catalogo"], cru)
    if base is None:
        return None, "payload de catálogo não reconhecido (era antiga?)"
    if not base.get("nome") or not base.get("url"):
        return None, "payload sem nome ou sem url"

    campos = dict.fromkeys(COLS_EVENTO)
    campos.update(base)
    campos.update({"id": f"{fonte}:{id_nativo}", "fonte": fonte,
                   "id_nativo": id_nativo,
                   # do cru, não de now(): é o momento REAL da coleta, e é a
                   # âncora do `sumido` (§6.5). E é `visto_em`, não
                   # `raspado_em`: o append-only só grava linha nova quando o
                   # payload MUDA, e "o evento ainda estava no catálogo" é
                   # avistamento, não mudança. Do CATÁLOGO só — descrever e
                   # precificar têm timestamp próprio e não provam presença no
                   # catálogo.
                   "raspado_em": cru["visto_em"] or cru["raspado_em"]})

    lotes = []
    for origem, payload in origens.items():
        conferir = modulo.CONFERIR.get(origem)
        if conferir and not conferir(payload, base):
            continue  # payload suspeito (id trocado / página redirecionada)
        derivacao = modulo.DERIVACOES.get(origem)
        if derivacao:
            campos.update({c: v for c, v in derivacao(payload).items()
                           if v is not None})
        extrator = modulo.LOTES.get(origem)
        if extrator:
            lotes.extend(extrator(payload))
    if lotes:
        campos.update(agregar(lotes))
    return (campos, lotes), None


def aplicar(con):
    """Reconstrói os eventos das 5 plataformas a partir do `cru`.

    A seco e idempotente: nenhuma requisição de rede, e rodar duas vezes dá o
    mesmo resultado. NÃO comita — quem comita é `tratamento/ciclo.py`, uma vez
    só no fim do ciclo (§8.1: enquanto o tratamento reconstrói, o site e o MCP
    continuam lendo `public`, que lê `tratado`).

    Retorna {coluna: quantos eventos ganharam valor} + "lotes" + "rejeitados"
    (payloads reprovados pela guarda, que viram erro na execução — silêncio
    aqui seria a fonte sumindo da base sem ninguém notar).
    """
    con.execute("DELETE FROM tratado.lotes")
    contagem = dict.fromkeys(
        [c for c in COLS_EVENTO if c not in ("id", "fonte", "id_nativo")], 0)
    contagem["lotes"] = 0
    rejeitados = []

    for fonte, modulo in TRILHAS.items():
        eventos, lotes_por_id = [], []
        for id_nativo, cru, origens in ler_cru(con, fonte):
            saida, motivo = _tratar(fonte, modulo, id_nativo, cru, origens)
            if saida is None:
                rejeitados.append({"evento_id": f"{fonte}:{id_nativo}",
                                   "erro": motivo})
                continue
            campos, lotes = saida
            eventos.append(campos)
            if lotes:
                lotes_por_id.append((campos["id"], lotes))
            for c, v in campos.items():
                if v is not None and c in contagem:
                    contagem[c] += 1
        if eventos:
            upsert_eventos(con, eventos)
        for evento_id, lotes in lotes_por_id:
            con.cursor().executemany(
                "INSERT INTO tratado.lotes (evento_id, ordem, nome, preco, "
                "taxa, gratis, esgotado) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [(evento_id, i, lt["nome"], lt["preco"], lt["taxa"],
                  1 if lt["gratis"] else 0, lt["esgotado"])
                 for i, lt in enumerate(lotes)])
            contagem["lotes"] += len(lotes)

    contagem["rejeitados"] = rejeitados
    return contagem


def normalizados(con, fonte):
    """O que o `cru` diz HOJE sobre cada evento de uma fonte, já normalizado:
    {id_nativo: campos de identidade}.

    É como a COLETA descobre para onde ir sem consultar `tratado`: o passo
    "descrever" precisa da URL, o "precificar" precisa da data. Ler daqui em
    vez da prata é o que permite os dois rodarem antes de qualquer escrita em
    `tratado` — e mantém UM só parser por fonte.
    """
    modulo = TRILHAS[fonte]
    saida = {}
    for id_nativo, cru, origens in ler_cru(con, fonte):
        base = modulo.normalizar(origens["catalogo"], cru)
        if base and base.get("nome") and base.get("url"):
            saida[id_nativo] = {
                **base, "origens": set(origens),
                "visto_em": cru["visto_em"] or cru["raspado_em"]}
    return saida
