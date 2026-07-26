"""API de leitura do site público — spec 20260726_abrir-ao-publico §2 e §3.

Por que existe: o front é Next.js (JavaScript) e a camada canônica é Python,
então o site não pode chamar `consulta.py` como função. Esta API é a ponte —
o mesmo papel que o `mcp_server.py` cumpre para a porta MCP.

NÃO TEM LÓGICA PRÓPRIA, e isso é o ponto: traduz querystring em argumentos de
consulta.py e devolve o que ela retorna. Dedupe, filtro de ruído, `sumido`,
`cancelado` e FTS continuam morando num lugar só. A alternativa (o Next ler o
Neon direto) foi explicitamente rejeitada na spec: duplicaria essas regras em
JavaScript e as duas cópias divergiriam na primeira mudança.

As duas únicas transformações que esta camada aplica são de POSTURA, não de
regra de negócio, e ambas decorrem da spec:

1. `descricao` sai em TRECHO, nunca integral (postura de ToS "agregador com
   atribuição", anexo tos.md). A tool MCP segue devolvendo o texto inteiro —
   ela serve um agente em contexto privado, não uma página indexada.
2. `organizador` NÃO é exposto. O campo às vezes carrega nome de pessoa física
   ("Fernando Chaves" está na base hoje), o que o traria para o escopo da LGPD
   numa página aberta. O design aprovado não usa o campo em tela nenhuma, então
   omiti-lo por completo é mais seguro e mais simples do que adivinhar por
   heurística quem é pessoa e quem é empresa.

Rotas (o vercel.json reescreve /api/dados/* para cá):
    /api/dados/eventos?texto=&de=&ate=&limite=&gratis=
    /api/dados/evento?url=
    /api/dados/filmes?texto=&cinema=&de=&ate=&limite=
    /api/dados/sessoes?filme=&cinema=
    /api/dados/procedencia
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import consulta  # noqa: E402  (precisa do sys.path acima)

# Trecho da descrição na página pública. Bem acima do corte da busca (300, que
# serve ao contexto do agente) e bem abaixo de "a descrição inteira": o
# suficiente para a pessoa entender o estilo do evento e decidir se abre o
# link, sem republicar o texto autoral do organizador.
DESCRICAO_SITE = 600

# Campos que a API nunca devolve, por decisão de postura (ver docstring).
OCULTOS = ("organizador",)

# A base muda 1x/dia (cron às 3h de Brasília). Cachear na CDN da Vercel
# protege o Neon, que hiberna no free tier e paga cold start a cada acordada.
# stale-while-revalidate longo: melhor servir dado de 1h enquanto revalida do
# que fazer o visitante esperar o banco acordar.
CACHE = "public, s-maxage=300, stale-while-revalidate=3600"
CACHE_CURTO = "public, s-maxage=60, stale-while-revalidate=600"


def _limpar(ev):
    """Aplica as duas transformações de postura a um evento."""
    if not isinstance(ev, dict):
        return ev
    ev = {k: v for k, v in ev.items() if k not in OCULTOS}
    d = ev.get("descricao")
    if d and len(d) > DESCRICAO_SITE:
        # corta na fronteira de palavra para não terminar no meio de uma
        corte = d.rfind(" ", 0, DESCRICAO_SITE)
        ev["descricao"] = d[:corte if corte > DESCRICAO_SITE // 2
                            else DESCRICAO_SITE].rstrip() + "…"
        ev["descricao_truncada"] = True
    return ev


def _int(q, nome, padrao, teto):
    """Inteiro da querystring, com teto — querystring é entrada de estranho."""
    try:
        return max(1, min(teto, int(q.get(nome, [padrao])[0])))
    except (ValueError, TypeError):
        return padrao


def _str(q, nome):
    v = (q.get(nome, [""])[0] or "").strip()
    return v or None


def _janela(q):
    """Traduz o atalho `periodo` em (de, ate) no fuso de Brasília.

    O dia da vida noturna não é o dia do calendário: uma festa que começa 1h
    de sábado pertence à noite de sexta. Por isso o corte do dia é às 6h
    locais, não à meia-noite — sem isso, "hoje" perderia metade da noite.
    """
    de, ate = _str(q, "de"), _str(q, "ate")
    if de or ate:
        return de, ate
    periodo = _str(q, "periodo")
    if not periodo:
        return None, None

    bsb = timezone(timedelta(hours=-3))
    agora = datetime.now(bsb)
    # antes das 6h ainda é "a noite de ontem"
    hoje = (agora - timedelta(hours=6)).date()
    virada = datetime.combine(hoje, datetime.min.time(), bsb) + timedelta(hours=6)

    if periodo == "hoje":
        return agora.isoformat(), (virada + timedelta(days=1)).isoformat()
    if periodo == "fds":
        # sexta 18h até a manhã de segunda; se já passou, o próximo fim de semana
        sexta = hoje - timedelta(days=(hoje.weekday() - 4) % 7)
        if hoje.weekday() < 4:  # seg-qui: o fds que vem
            sexta = hoje + timedelta(days=4 - hoje.weekday())
        ini = datetime.combine(sexta, datetime.min.time(), bsb) + timedelta(hours=18)
        return max(ini, agora).isoformat(), (ini + timedelta(days=2, hours=12)).isoformat()
    if periodo == "7d":
        return agora.isoformat(), (virada + timedelta(days=7)).isoformat()
    return None, None


def rota(caminho, q):
    """Despacha a rota. Devolve (payload, cache) ou levanta KeyError."""
    if caminho.endswith("/eventos"):
        de, ate = _janela(q)
        evs = consulta.buscar_eventos(
            texto=_str(q, "texto"), cidade="Brasília",
            data_inicio=de, data_fim=ate, limite=_int(q, "limite", 60, 200))
        if _str(q, "gratis"):
            # tem_gratis = há lote grátis não esgotado; preco_min NULL junto
            # significa evento sem cobrança. Filtrar aqui e não no SQL mantém
            # a consulta.py com uma responsabilidade só.
            evs = [e for e in evs if e.get("tem_gratis") == 1]
        return {"eventos": [_limpar(e) for e in evs]}, CACHE

    if caminho.endswith("/evento"):
        url = _str(q, "url")
        if not url:
            return {"erro": "informe ?url="}, CACHE_CURTO
        ev = consulta.detalhar_evento(url)
        return _limpar(ev), CACHE

    if caminho.endswith("/filmes"):
        de, ate = _janela(q)
        return {"filmes": consulta.buscar_filmes(
            texto=_str(q, "texto"), data_inicio=de, data_fim=ate,
            cinema=_str(q, "cinema"), limite=_int(q, "limite", 40, 100))}, CACHE

    if caminho.endswith("/sessoes"):
        filme = _str(q, "filme")
        if not filme:
            return {"erro": "informe ?filme="}, CACHE_CURTO
        de, ate = _janela(q)
        return consulta.sessoes_filme(
            filme, data_inicio=de, data_fim=ate, cinema=_str(q, "cinema")), CACHE

    if caminho.endswith("/procedencia"):
        return {"fontes": consulta.procedencia()}, CACHE_CURTO

    raise KeyError(caminho)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        alvo = urlparse(self.path)
        try:
            payload, cache = rota(alvo.path, parse_qs(alvo.query))
            status = 400 if isinstance(payload, dict) and "erro" in payload else 200
        except KeyError:
            payload, cache, status = {"erro": "rota desconhecida"}, CACHE_CURTO, 404
        except Exception as e:  # noqa: BLE001 — a falha não pode derrubar a página
            payload = {"erro": f"{type(e).__name__}: {e}"}
            cache, status = "no-store", 500

        corpo = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        # Leitura pública: liberar CORS deixa o front chamar do cliente sem
        # proxy, além do SSR.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *_):
        pass  # o log da Vercel já registra a requisição


if __name__ == "__main__":
    # Servidor local para desenvolver o front sem depender de deploy:
    #     python api/dados.py            (porta 8000)
    # Na Vercel quem instancia o handler é a plataforma; isto é só o atalho
    # de dev, e por isso não tem nenhuma configuração além da porta.
    from http.server import HTTPServer

    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"API de leitura em http://localhost:{porta}/api/dados/eventos")
    HTTPServer(("127.0.0.1", porta), handler).serve_forever()
