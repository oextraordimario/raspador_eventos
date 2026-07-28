"""Raspador da programação de cinema de Brasília via API de conteúdo da
Ingresso.com (api-content.ingresso.com, sem auth, sem navegador).

Descoberta (spike spikes/cinema/, 2026-07-11): os 8 cinemas-alvo do usuário
vendem via Ingresso.com — Cinesystem e Kinoplex inclusive fazem checkout lá —
e o endpoint de sessões devolve a grade completa por cinema×dia:

  GET /v0/sessions/city/12/theater/{id}?date=YYYY-MM-DD

com filme (título, gêneros, duração, classificação, pôster, trailer) e sessões
por sala (horário local -03:00, tipos 2D/3D/XD/VIP/DUB/LEG, preço, link de
compra). cityId 12 = Brasília. **404 = dia sem programação** (Cine Brasília
fecha alguns dias), não erro.

Contrato próprio (difere dos scrapers de eventos — devolve a grade bruta, não
lista normalizada): raspar() → {"raw": [(cinema_id, dia, payload)], "erros"}.
Quem grava é gravar.gravar_cinema_raw; quem normaliza é derivar.aplicar_cinema
(snapshot: trunca e reconstrói filmes/sessoes). Fallbacks por rede, se esta
API quebrar: spikes/cinema/README.md. Spec: docs/specs/20260711_raspagem-cinema/.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api-content.ingresso.com/v0/sessions/city/12/theater/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Brasília é UTC-3 fixo (sem horário de verão desde 2019). A API pagina por
# data LOCAL — "hoje" tem que ser o hoje de Brasília, não o de UTC.
FUSO_BRASILIA = timezone(timedelta(hours=-3))

# Os 8 cinemas-alvo (lista do usuário, 2026-07-11), theaterId -> apelido
# canônico. "Cinesystem Caixa Brasília" é o nome oficial do CasaPark na API
# (naming rights); o endereço (SGCV Lote 22, Guará) confirma que é ele.
CINEMAS = {
    "847": "Cinemark Iguatemi",
    "128": "Cinemark Pier 21",
    "124": "Kinoplex ParkShopping",
    "126": "Kinoplex Pátio Brasil",
    "833": "Kinoplex Boulevard",
    "1605": "Cinesystem CasaPark",
    "1583": "Cine Brasília",
    "1538": "Cine Cultura Liberty Mall",
}


def _get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def sessoes_do_dia(cinema_id, dia):
    """Grade de um cinema num dia: lista de blocos-dia da API (normalmente 1).

    404 = dia sem programação → lista vazia (não é erro). Outros erros de
    rede/HTTP sobem — o chamador decide tolerar.
    """
    try:
        dados = _get(f"{API}{cinema_id}?date={dia}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return dados if isinstance(dados, list) else []


# Estatísticas da última chamada a raspar(), para o relatório de cobertura do
# atualizar.py (coletados = cinemas que responderam ao menos um dia).
ULTIMA_RASPAGEM = {}


def raspar(dias=8, pausa=0.3):
    """Raspa a grade dos 8 cinemas para `dias` corridos (hoje local → +dias-1).

    8 dias cobrem a semana útil da programação (que vira na quinta); além da
    próxima quarta a API só traz pré-vendas — entram como filmes em_pre_venda.

    Retorna {"raw": [(cinema_id, dia, payload)], "erros": [{cinema, dia, erro}]}.
    Cinema×dia que falhou fica FORA de raw — o chamador preserva o payload
    anterior daquele par em vez de gravar buraco.
    """
    hoje = datetime.now(FUSO_BRASILIA).date()
    datas = [(hoje + timedelta(days=n)).isoformat() for n in range(dias)]
    raw, erros = [], []
    responderam = set()
    for cinema_id, apelido in CINEMAS.items():
        falhas_antes = len(erros)
        for dia in datas:
            try:
                blocos = sessoes_do_dia(cinema_id, dia)
            except Exception as e:
                erros.append({"cinema": apelido, "dia": dia,
                              "erro": f"{type(e).__name__}: {e}"})
                continue
            raw.append((cinema_id, dia, blocos))
            responderam.add(cinema_id)
            time.sleep(pausa)
        falhas = len(erros) - falhas_antes
        print(f"  {apelido}: " +
              ("ok" if not falhas else f"{falhas}/{len(datas)} dias falharam"))
    ULTIMA_RASPAGEM.update(coletados=len(responderam),
                           total_site=len(CINEMAS))
    return {"raw": raw, "erros": erros}
