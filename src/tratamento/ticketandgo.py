"""Tratamento do TICKET AND GO: payload de `cru.ticketandgo` → `tratado.lotes`.

Este arquivo sabe LER o Ticket and Go; `coleta/ticketandgo.py` sabe FALAR com
ele.

DUAS ERAS DE PAYLOAD (spec §6.3). A API V1 foi desligada em 2026-07-28 e 5 dos
payloads de catálogo guardados são dela, com schema completamente diferente
(`slug`, `endereco_completo`, `latitude` em vez de `slug_evento` e sem
endereço). O parser novo aplicado a eles NÃO falha — acha `nome` e `inicio` por
coincidência de nome de campo e degrada em silêncio, perdendo o endereço e
montando uma URL sem slug.

A coluna `cru.ticketandgo.api` resolve isso para a frente: a coleta declara qual
endpoint chamou. Para o passado (`api IS NULL`) vale `tolerar_era()` abaixo.

A tolerância mora aqui porque a diferença é de LEITURA do payload, não de
coleta — e desde a fatia 7 é `normalizar()` abaixo quem a consome, ao produzir
endereço e lat/lon.
"""

from base import texto

# Brasília é UTC-3 o ano inteiro (o DF não tem horário de verão desde 2019).
FUSO_BRASILIA = "-03:00"


def quando(data, hora):
    """Compõe data + hora LOCAIS da fonte em ISO com o fuso de Brasília.

    A fonte manda "2026-08-29" e "19:00:00" separados e sem fuso — este é o
    único lugar do projeto que sabe disso. Aceita data já com hora embutida por
    robustez; sem hora, assume 00:00 (a data já serve ao filtro por dia).

    Vive no tratamento e é importada pela coleta (que a usa no filtro de
    futuros): a direção proibida é a coleta ESCREVER em `tratado`, não ler uma
    função pura daqui. Duas cópias divergiriam.
    """
    if not data:
        return None
    data = data.strip()
    base = data.replace(" ", "T") if (" " in data or "T" in data) \
        else f"{data}T{(hora or '00:00:00').strip()}"
    return f"{base}{FUSO_BRASILIA}"


# Valor-padrão do `nome_tipo_evento` da fonte: 71 dos 72 eventos categorizados
# são só "Evento" (medido em 2026-07-28). Guardá-lo é repetir o antipadrão que
# a §6.2 desmontou no `event_type`='NORMAL' do Sympla — rótulo sem poder de
# distinção que só polui o FTS. O que NÃO é o padrão continua valendo: a fonte
# às vezes escreve algo real ali ("Conquistadoras – meninas de 13 a 17 anos").
_CATEGORIA_GENERICA = "evento"


def _categoria(p):
    cat = (p.get("nome_tipo_evento") or "").strip()
    return cat or None if cat.casefold() != _CATEGORIA_GENERICA else None


def normalizar(p, cru):
    """Detalhe da fonte → as colunas de IDENTIDADE do evento (era
    `coleta/ticketandgo._normalizar`). None = payload não reconhecido (§6.3).

    `slug`, `cidade` e `estado` vêm das colunas próprias de `cru.ticketandgo`,
    não do payload: a fonte não expõe mais endereço (a V1 foi desligada), então
    quem decidiu que o evento é do DF foi o `_do_df` da coleta, e o slug não é
    derivável do id numérico. Endereço e lat/lon só existem nos payloads da era
    V1 — `tolerar_era` os recupera e devolve None para os da V2.
    """
    if str(p.get("id") or "").strip() != cru["id_nativo"]:
        return None
    era = tolerar_era(p)
    slug = cru.get("slug") or era["slug"]
    return {
        "nome": p.get("nome"),
        "start_date": quando(p.get("inicio"), p.get("hora_incio")),
        "end_date": quando(p.get("fim"), p.get("hora_fim")),
        "cidade": cru.get("cidade_label"),
        "estado": cru.get("estado_label"),
        "local_nome": (p.get("local") or "").strip() or None,
        "endereco": era["endereco"],
        "lat": era["lat"],
        "lon": era["lon"],
        "categoria": _categoria(p),
        "organizador": None,  # produtora é razão social (pessoa jurídica/física)
        "url": (f"https://www.ticketandgo.com.br/evento/{slug}" if slug
                else None),
        "imagem": p.get("banner") or p.get("imagem") or None,
        # descrição já vem no detalhe — sem passo "descrever" p/ esta fonte
        "descricao": texto.limpar_html(p.get("descricao")),
    }


def tolerar_era(p):
    """Lê os campos que MUDARAM de nome entre a V1 e a V2, aceitando os dois.

    Devolve {slug, endereco, lat, lon} — os quatro que a V2 deixou de expor ou
    renomeou. Não inventa nada: campo ausente nas duas eras vira None.
    """
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "slug": p.get("slug_evento") or p.get("slug") or None,
        "endereco": (p.get("endereco_completo") or p.get("endereco")
                     or None),
        "lat": num(p.get("latitude")),
        "lon": num(p.get("longitude")),
    }


def lotes(p):
    """Detalhe do evento: os lotes vêm em bilhetes[] (evento simples) OU
    aninhados em setores[].bilhetes[] (evento com setor — nome vira
    "setor — lote", como no Ingresse).

    `taxa_conveniencia` é FRAÇÃO sobre o valor (0.1 = 10%), não reais —
    normalizamos `preco` para o total a pagar (valor + valor×fração). A fonte
    só lista lote à venda (sem flag de esgotado no payload), então `esgotado`
    fica 0.
    """
    try:
        fracao = float(p.get("taxa_conveniencia"))
    except (TypeError, ValueError):
        fracao = None
    grupos = [("", p.get("bilhetes") or [])]
    grupos += [((s.get("nome") or "").strip(), s.get("bilhetes") or [])
               for s in (p.get("setores") or []) if isinstance(s, dict)]
    saida = []
    for setor, bilhetes in grupos:
        for b in bilhetes:
            if not isinstance(b, dict):
                continue
            try:
                valor = float(b.get("valor_bilhete") or b.get("valor"))
            except (TypeError, ValueError):
                valor = None
            taxa = round(valor * fracao, 2) if (valor and fracao) else None
            preco = valor + (taxa or 0.0) if valor is not None else None
            nome = (b.get("nome") or "").strip() or None
            if setor and nome and setor.casefold() != nome.casefold():
                nome = f"{setor} — {nome}"
            elif setor and not nome:
                nome = setor
            saida.append({"nome": nome, "preco": preco, "taxa": taxa,
                          "gratis": preco == 0, "esgotado": 0})
    return saida


DERIVACOES = {}
LOTES = {"tickets": lotes}
CONFERIR = {}
