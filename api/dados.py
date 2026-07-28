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
    GET  /api/dados/eventos?texto=&de=&ate=&limite=&gratis=&bairro=&tipo=&perto=
    GET  /api/dados/evento?url=
    GET  /api/dados/filmes?texto=&cinema=&de=&ate=&limite=
    GET  /api/dados/sessoes?filme=&cinema=
    GET  /api/dados/procedencia
    POST /api/dados/feedback          (form urlencoded — a ÚNICA escrita)

O `do_POST` chegou em 2026-07-28 com o canal de feedback (NI-52). Ele não
quebra a regra da docstring: quem decide o que é um envio válido, o que é
abuso e o que vira linha é `servico/feedback.py`; aqui se lê o corpo do
formulário e se traduz o resultado em status HTTP.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from base import conexao  # noqa: E402  (precisa do sys.path acima)
from servico import consulta  # noqa: E402
from servico import feedback as svc_feedback  # noqa: E402

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


def _perto(q):
    """`?perto=<lat>,<lon>` → (lat, lon) ou (None, None).

    A coordenada de quem está perguntando entra pela querystring, é usada na
    ordenação e NÃO é gravada nem logada em lugar nenhum — nem aqui, nem no
    analytics do front (o parâmetro entra na lista de mascarados do PostHog;
    ver app/PertoDeMim.jsx). É o compromisso declarado na página /sobre.

    Fora do DF a resposta continua sendo Brasília ordenada por distância —
    inútil, mas não errado —, então não há validação de área. O que se valida
    é o formato: número, e dentro do planeta.
    """
    bruto = _str(q, "perto")
    if not bruto:
        return None, None
    try:
        lat, lon = (float(x) for x in bruto.split(",", 1))
    except (ValueError, TypeError):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


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
    if periodo == "proximos":
        # a agenda inteira daqui para frente: sem limite superior, mas COM o
        # inferior — sem `de` a consulta não filtra data nenhuma e o passado
        # voltaria para a página.
        return agora.isoformat(), None
    return None, None


def rota(caminho, q, con=None):
    """Despacha a rota. Devolve (payload, cache) ou levanta KeyError.

    `con` é a conexão da REQUISIÇÃO, aberta uma vez pelo handler e repassada a
    todas as consultas da rota (ver consulta._con). Sem ela cada consulta abria
    a sua — e a rota de cinema faz duas, pagando dois handshakes com o Neon por
    render. Omitida (testes, uso direto), cada consulta se vira sozinha.
    """
    if caminho.endswith("/eventos"):
        de, ate = _janela(q)
        plat, plon = _perto(q)
        evs = consulta.buscar_eventos(
            texto=_str(q, "texto"), cidade="Brasília",
            data_inicio=de, data_fim=ate, limite=_int(q, "limite", 60, 200),
            bairro=_str(q, "bairro"), tipo=_str(q, "tipo"),
            gratis=bool(_str(q, "gratis")), perto_lat=plat, perto_lon=plon,
            con=con)
        # As facetas vão na MESMA resposta, como já vão em /filmes: a página
        # monta o calendário sem um segundo round-trip, e elas entram no mesmo
        # objeto cacheado pela CDN.
        return {"eventos": [_limpar(e) for e in evs],
                "facetas": consulta.facetas_eventos(cidade="Brasília",
                                                    con=con)}, CACHE

    if caminho.endswith("/evento"):
        url = _str(q, "url")
        if not url:
            return {"erro": "informe ?url="}, CACHE_CURTO
        ev = consulta.detalhar_evento(url, con=con)
        return _limpar(ev), CACHE

    if caminho.endswith("/filmes"):
        de, ate = _janela(q)
        # hora_de/hora_ate: None quando ausentes (0 é valor válido — meia-noite)
        hora_de = _str(q, "hora_de")
        hora_ate = _str(q, "hora_ate")
        # As facetas vão na MESMA resposta (e não numa rota própria) para a
        # página montar os filtros sem segundo round-trip; multi-valor chega
        # como CSV e desce como veio — quem entende vírgula é a consulta.
        return {"filmes": consulta.buscar_filmes(
            texto=_str(q, "texto"), data_inicio=de, data_fim=ate,
            cinema=_str(q, "cinema"), generos=_str(q, "generos"),
            classificacao=_str(q, "classificacao"),
            hora_de=int(hora_de) if hora_de and hora_de.isdigit() else None,
            hora_ate=int(hora_ate) if hora_ate and hora_ate.isdigit() else None,
            limite=_int(q, "limite", 40, 100), con=con),
            "facetas": consulta.facetas_filmes(con=con)}, CACHE

    if caminho.endswith("/sessoes"):
        filme = _str(q, "filme")
        if not filme:
            return {"erro": "informe ?filme="}, CACHE_CURTO
        de, ate = _janela(q)
        hora_de = _str(q, "hora_de")
        hora_ate = _str(q, "hora_ate")
        return consulta.sessoes_filme(
            filme, data_inicio=de, data_fim=ate, cinema=_str(q, "cinema"),
            hora_de=int(hora_de) if hora_de and hora_de.isdigit() else None,
            hora_ate=int(hora_ate) if hora_ate and hora_ate.isdigit() else None,
            con=con,
        ), CACHE

    if caminho.endswith("/procedencia"):
        return {"fontes": consulta.procedencia(con=con)}, CACHE_CURTO

    raise KeyError(caminho)


# Corpo de POST também é entrada de estranho: sem teto, um cliente qualquer
# mandaria megabytes e a função leria tudo na memória antes de validar.
CORPO_MAX = 16 * 1024


def rota_post(caminho, campos):
    """Despacha um POST. Devolve (destino, status) — sempre um redirect.

    **Sempre 303, inclusive no caminho triste**, e isso é decisão, não
    esquecimento: o cliente desta rota é um `<form method="post">` NATIVO, sem
    fetch, porque é o único jeito de o canal funcionar sem JS. Um 400/429 seco
    mostraria JSON cru na tela de quem preencheu o formulário. O que o teto por
    janela precisa garantir — que a enxurrada não vire linha na base — é
    garantido igual; o robô não lê o status de qualquer forma.
    """
    if caminho.endswith("/feedback"):
        tipo = _str(campos, "tipo") or ""
        r = svc_feedback.registrar(
            tipo=tipo,
            mensagem=_str(campos, "mensagem"),
            contato=_str(campos, "contato"),
            pagina=_str(campos, "pagina"),
            isca=_str(campos, "site"),   # honeypot: ver servico/feedback.py
        )
        if r.get("ok"):
            # o `tipo` volta na URL só para a página poder instrumentar o envio
            # (§9 da spec). A mensagem e o contato NUNCA saem daqui.
            return f"/feedback?ok=1&tipo={quote(tipo)}", 303
        return f"/feedback?erro={r['erro']}", 303

    raise KeyError(caminho)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        alvo = urlparse(self.path)
        # UMA conexão por requisição, repassada a todas as consultas da rota
        # (ver `rota`). Abrir tarde e fechar sempre: rota desconhecida não
        # chega a usá-la, e conexão vazada seria pior que o handshake.
        con = None
        try:
            con = conexao.conectar()
            payload, cache = rota(alvo.path, parse_qs(alvo.query), con=con)
            status = 400 if isinstance(payload, dict) and "erro" in payload else 200
        except KeyError:
            payload, cache, status = {"erro": "rota desconhecida"}, CACHE_CURTO, 404
        except Exception as e:  # noqa: BLE001 — a falha não pode derrubar a página
            payload = {"erro": f"{type(e).__name__}: {e}"}
            cache, status = "no-store", 500
        finally:
            if con is not None:
                con.close()

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

    def do_POST(self):
        alvo = urlparse(self.path)
        try:
            tam = min(int(self.headers.get("Content-Length") or 0), CORPO_MAX)
            corpo = self.rfile.read(tam).decode("utf-8", "replace")
            destino, status = rota_post(alvo.path, parse_qs(corpo))
        except KeyError:
            destino, status = None, 404
        except Exception as e:  # noqa: BLE001 — nem o erro pode virar 500 na cara
            print(f"feedback: {type(e).__name__}: {e}", file=sys.stderr)
            destino, status = "/feedback?erro=interno", 303

        self.send_response(status)
        if destino:
            self.send_header("Location", destino)
        # escrita nunca é cacheável — nem a resposta, nem a página de destino
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

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
