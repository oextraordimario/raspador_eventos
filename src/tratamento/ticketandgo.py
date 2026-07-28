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
coleta. As colunas afetadas (url, endereço, lat/lon) só passam por este módulo
quando a normalização migrar para cá, na fatia 7 — até lá `tolerar_era` é usada
pelo modo conferência, que é justamente quem compara as duas leituras.
"""


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
