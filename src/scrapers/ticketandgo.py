"""Raspador do Ticket and Go (ticketandgo.com.br) via API interna do site.

Descoberta (spike spikes/zig-ticketandgo/, 2026-07-12): o site é um SPA
Vue/Vite atrás de queue-it (como o Ingresse); a API de leitura é aberta:

  POST https://production-api-v1-service.ticketandgo.com.br/eventos/pesquisa
       body {"pesquisa": ""}  -> o CATÁLOGO INTEIRO (~460 eventos), cada um
       já com a descrição HTML completa — esta fonte não precisa do passo
       "descrever" do atualizar.py (como o Shotgun).
  GET  https://production-api-v1-service.ticketandgo.com.br/eventos/{slug}
       -> detalhe com "bilhetes" (lotes: nome + valor) e "taxa_conveniencia"
       (fração, ex.: 0.1 = 10%) — é o payload do passo "precificar".

Particularidades da fonte:
- cidade/estado/cep vêm NULOS no catálogo; o local mora nos textos `local` e
  `endereco_completo` ("SCTN - Plano Piloto, Brasília - DF, 70040-010").
  O filtro de DF é textual (_do_df) e cidade/estado são ROTULADOS pelo filtro,
  como o Shotgun rotula pela cidade pesquisada.
- datas separadas e SEM fuso: inicio/fim "YYYY-MM-DD" + hora_incio/hora_fim
  "HH:MM:SS" (typo da fonte, sem o segundo "i") em hora local de Brasília —
  _quando compõe "YYYY-MM-DDTHH:MM:SS-03:00"; o upsert normaliza para UTC.
"""

import html
import re
import time
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://production-api-v1-service.ticketandgo.com.br"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Brasília é UTC-3 o ano inteiro (o DF não tem horário de verão desde 2019).
FUSO_BRASILIA = "-03:00"

# CEPs do DF começam em 70–73 (Brasília e cidades-satélites).
_CEP_DF = re.compile(r"\b7[0-3]\d{3}-?\d{3}\b")
_UF_DF = re.compile(r"\bDF\b")


def _requisitar(url, body=None):
    dados = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=dados,
        headers={"User-Agent": UA, "Accept": "application/json",
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


def _do_df(ev):
    """Filtro textual de DF sobre local/endereco_completo (cidade/uf nulos na
    fonte). Erra para o lado de PERDER evento sem marca de DF no endereço,
    nunca de poluir a base com outra cidade. Calibrado no spike (102/102)."""
    texto = f"{ev.get('local') or ''} {ev.get('endereco_completo') or ''}"
    return bool("brasília" in texto.casefold() or _UF_DF.search(texto)
                or _CEP_DF.search(texto))


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
    """Busca o detalhe do evento (bilhetes/lotes + taxa_conveniencia) pelo
    slug da URL publica. Retorna {"payload": data do detalhe} para a camada
    Bronze; quem transforma em lotes/preco_min é o derivar. Levanta excecao
    em erro de rede/HTTP."""
    resp = _requisitar(f"{API}/eventos/{urllib.parse.quote(slug)}")
    return {"payload": resp.get("data") or {}}


def _normalizar(ev, cidade_label, estado_label):
    id_nativo = str(ev.get("id"))
    slug = ev.get("slug")
    return {
        "id": f"ticketandgo:{id_nativo}",
        "fonte": "ticketandgo",
        "id_nativo": id_nativo,
        "nome": ev.get("nome"),
        "start_date": _quando(ev.get("inicio"), ev.get("hora_incio")),
        "end_date": _quando(ev.get("fim"), ev.get("hora_fim")),
        # rotulados pelo filtro _do_df (a fonte manda cidade/estado nulos)
        "cidade": cidade_label,
        "estado": estado_label,
        "local_nome": (ev.get("local") or "").strip() or None,
        "endereco": (ev.get("endereco_completo") or "").strip() or None,
        "lat": ev.get("latitude") or None,
        "lon": ev.get("longitude") or None,
        "categoria": (ev.get("nome_tipo_evento") or "").strip() or None,
        "organizador": None,  # a fonte só expõe id_produtora no catálogo
        "url": f"https://www.ticketandgo.com.br/evento/{slug}" if slug else None,
        "imagem": ev.get("banner") or ev.get("imagem") or None,
        "raspado_em": datetime.now(timezone.utc).isoformat(),
        # descrição já vem no catálogo — sem passo "descrever" p/ esta fonte
        "descricao": _limpar_html(ev.get("descricao")),
        "_raw": ev,  # payload bruto -> eventos_raw (camada Bronze)
    }


def _futuro(ev):
    quando = _quando(ev.get("fim"), ev.get("hora_fim")) \
        or _quando(ev.get("inicio"), ev.get("hora_incio"))
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


def raspar(cidade_label="Brasília", estado_label="DF", pausa=0.0,
           apenas_futuros=True):
    """Baixa o catálogo inteiro (pesquisa vazia), filtra DF e normaliza."""
    resp = _requisitar(f"{API}/eventos/pesquisa", body={"pesquisa": ""})
    catalogo = (resp.get("data") or {}).get("eventos") or []
    df = [ev for ev in catalogo if _do_df(ev)]
    vistos = {}
    for ev in df:
        if apenas_futuros and not _futuro(ev):
            continue
        norm = _normalizar(ev, cidade_label, estado_label)
        vistos.setdefault(norm["id"], norm)
    print(f"  catálogo: {len(catalogo)} eventos | DF: {len(df)} | "
          f"futuros normalizados: {len(vistos)}")
    if pausa:
        time.sleep(pausa)
    ULTIMA_RASPAGEM.update(total_site=len(df), coletados=len(vistos))
    return list(vistos.values())
