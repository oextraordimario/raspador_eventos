"""MCP server que expõe a base unificada de eventos como tools para um agente de IA.

Dois transportes (a base é a mesma — o Neon):
- stdio (default) — clientes locais (Claude Code, Claude Desktop, Codex) e o
  test_mcp_server.py. Rodar manualmente para depurar: python src/mcp_server.py
- streamable HTTP (--http) — o MCP REMOTO da Fase 0b (NI-20): stateless (casa
  com serverless que escala a zero), na porta da env PORT. Com OAuth (NI-11)
  ele fica em https://<host>/mcp; sem, cai no modo antigo, sob o prefixo de
  rota secreto da env MCP_SEGREDO.
  Specs: docs/specs/20260711_consulta-na-nuvem/, 20260726_abrir-ao-publico/.

As tools são finas: delegam para a camada de consulta (consulta.py).
"""

import functools
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from pathlib import Path

# Entrypoint (stdio e --http) e também módulo importado por api/index.py: põe
# src/ no sys.path para os pacotes de estágio resolverem.
_SRC = str(Path(__file__).resolve().parents[1])
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from base import conexao  # noqa: E402
from servico import consulta  # noqa: E402
# Ligado por ENV, não por flag de linha de comando: o MESMO módulo serve o
# stdio local (sem auth — a identidade é o dono da máquina) e o remoto na
# Vercel (com auth). Faltando qualquer uma das duas envs, o servidor sobe sem
# auth e o transporte HTTP volta ao prefixo secreto — que é também o caminho
# de rollback, sem tocar em código.
AUTHKIT_ISSUER = conexao.env_var("AUTHKIT_ISSUER")   # https://<sub>.authkit.app
MCP_RECURSO = conexao.env_var("MCP_RECURSO")         # https://<host>/mcp


def _servidor():
    if not (AUTHKIT_ISSUER and MCP_RECURSO):
        return FastMCP("eventos-brasilia")

    from mcp.server.auth.settings import AuthSettings

    from auth import VerificadorAuthKit

    # `resource_server_url` é a URL PÚBLICA do endpoint MCP, não a raiz do
    # site: é dela que o SDK deriva a rota de metadados exigida pela RFC 9728
    # (/.well-known/oauth-protected-resource/mcp) e o aud esperado no token.
    return FastMCP(
        "eventos-brasilia",
        token_verifier=VerificadorAuthKit(AUTHKIT_ISSUER, MCP_RECURSO),
        auth=AuthSettings(issuer_url=AUTHKIT_ISSUER,
                          resource_server_url=MCP_RECURSO,
                          required_scopes=[]),
    )


mcp = _servidor()

_DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"]

# ── Instrumentação (NI-11) ────────────────────────────────────────────────
# O critério das Fases 1 e 2 do PRD não fecha por percepção: sem registro, "um
# conhecido usou" vira achismo. O que se registra é a INTENÇÃO (a tool e seus
# argumentos, incluindo o texto buscado) — é o insumo de produto da abertura,
# não só contagem de tráfego.
#
# Já funciona hoje, sem OAuth: a chamada entra em `acessos` com sub NULL. Com o
# NI-11 no ar, o mesmo decorator passa a resolver a identidade e aplicar teto.

# Teto por usuário/hora. Existe porque a URL do connector fica pública: é a
# defesa do free tier do Neon contra uso anômalo. 120 é folgado para uso humano
# via agente e apertado para laço automático.
LIMITE_HORA = 120


def _identidade():
    """(sub, email) de quem chamou, ou (None, None) em chamada local.

    É o ÚNICO ponto onde o token vira identidade. Sem OAuth configurado (stdio
    local, ou remoto ainda no prefixo secreto) devolve (None, None) e a chamada
    entra em `acessos` anônima — a instrumentação segue funcionando.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
        token = get_access_token()
        if not token:
            return None, None
        claims = token.claims or {}
        return token.subject or claims.get("sub"), claims.get("email")
    except Exception:
        # stdio ou fora de contexto de request: chamada local. Nunca derruba a
        # tool por causa da instrumentação.
        return None, None


def _registrar(sub, tool, args, resultados, ms, erro):
    con = None
    try:
        con = conexao.conectar()
        con.execute(
            "INSERT INTO uso.acessos (sub, em, tool, args, resultados, ms, erro) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (sub, datetime.now(timezone.utc).isoformat(), tool,
             json.dumps(args, ensure_ascii=False, default=str)[:2000],
             resultados, ms, erro))
        con.commit()
    except Exception as e:  # noqa: BLE001
        # Instrumentação NUNCA pode derrubar a consulta: se a tabela não existe
        # (base antiga) ou a escrita falha, a resposta ao agente segue igual.
        print(f"[instrumentacao] falhou: {type(e).__name__}: {e}",
              file=sys.stderr)
    finally:
        if con is not None:
            con.close()


def registrado(fn):
    """Cronometra a tool, grava em `acessos` e aplica bloqueio/teto por usuário.

    As tools continuam finas: todo o peso fica confinado aqui, e a consulta.py
    segue intocada.
    """
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        sub, email = _identidade()

        if sub:
            try:
                con = conexao.conectar()
                u = con.execute(
                    "SELECT bloqueado FROM uso.usuarios WHERE sub = %s",
                    (sub,)).fetchone()
                agora = datetime.now(timezone.utc)
                if u is None:
                    con.execute(
                        "INSERT INTO uso.usuarios (sub, email, criado_em, visto_em)"
                        " VALUES (%s, %s, %s, %s) ON CONFLICT (sub) DO NOTHING",
                        (sub, email, agora.isoformat(), agora.isoformat()))
                else:
                    if u["bloqueado"]:
                        con.commit()
                        con.close()
                        # erro de DADO, não exceção de transporte: o agente
                        # precisa conseguir explicar isso a quem perguntou.
                        return {"erro": "Acesso suspenso."}
                    con.execute("UPDATE uso.usuarios SET visto_em = %s WHERE sub = %s",
                                (agora.isoformat(), sub))
                corte = (agora - timedelta(hours=1)).isoformat()
                n = con.execute(
                    "SELECT COUNT(*) AS n FROM uso.acessos WHERE sub = %s AND em >= %s",
                    (sub, corte)).fetchone()["n"]
                con.commit()
                con.close()
                if n >= LIMITE_HORA:
                    return {"erro": "Limite de consultas por hora atingido. "
                                    "Tente daqui a pouco."}
            except Exception as e:  # noqa: BLE001
                print(f"[instrumentacao] identidade: {type(e).__name__}: {e}",
                      file=sys.stderr)

        inicio = time.monotonic()
        erro, r = None, None
        try:
            r = fn(*a, **kw)
            return r
        except Exception as e:  # noqa: BLE001
            erro = f"{type(e).__name__}: {e}"
            raise
        finally:
            ms = int((time.monotonic() - inicio) * 1000)
            n = len(r) if isinstance(r, list) else None
            _registrar(sub, fn.__name__, kw or {"args": a}, n, ms, erro)

    return wrapper


@mcp.tool()
@registrado
def buscar_eventos(texto: str = "", cidade: str = "Brasília",
                   data_inicio: str = "", data_fim: str = "",
                   bairro: str = "", tipo: str = "", gratis: bool = False,
                   limite: int = 20) -> list[dict]:
    """Busca festas, baladas e shows em Brasília na base unificada (Sympla,
    Ingresse, Shotgun, Zig e Ticket and Go). Use para responder o que há de
    festa/balada/show numa
    cidade e período. Todos os argumentos são opcionais. A base já vem limpa:
    anúncios/cursos, eventos cancelados e eventos que sumiram do catálogo da
    fonte (provável cancelamento silencioso) são filtrados, e o mesmo evento
    publicado em mais de uma plataforma vem colapsado num único resultado
    (campo outras_urls traz os links dele nas demais plataformas, quando
    houver).

    Args:
        texto: termos de busca no nome, atrações e descrição do evento (sintaxe
            FTS5, ex.: "pagode", "funk OR techno", "eletrônica"). Acha o termo
            mesmo quando ele só aparece na descrição. Vazio = qualquer evento.
        cidade: cidade do evento (padrão "Brasília"; hoje a base só cobre Brasília).
        data_inicio: início da janela, ISO 8601 (ex.: "2026-07-10T00:00:00+00:00").
            Vazio = sem limite inferior. Para "só eventos futuros", passe o horário
            atual — obtenha-o com a tool data_atual.
        data_fim: fim da janela, ISO 8601. Vazio = sem limite superior.
        bairro: bairro/região de Brasília, texto exato ou vários separados por
            vírgula ("Asa Sul", "Asa Norte,Sudoeste"). Cerca de metade dos
            eventos tem bairro conhecido — quem não tem fica FORA do resultado
            quando este filtro é usado, então prefira a busca textual quando o
            usuário citar a casa em vez da região.
        tipo: "festa" (festas e baladas) ou "show" (shows e festivais). A
            classificação é heurística e cobre só parte da agenda, então o
            filtro traz TAMBÉM os eventos sem classificação — ele afunila, não
            garante. Vazio = tudo.
        gratis: True devolve só eventos com lote grátis disponível.
        limite: número máximo de resultados (padrão 20), ordenados por data.

    Returns:
        Lista de eventos com nome, fonte, start_date, end_date, cidade, local,
        bairro, categoria, organizador, url, atracoes (line-up), preco_min
        (menor lote PAGO, em R$ totais com taxa; null = sem lote pago ou fonte
        não informou), tem_gratis (1 = há lote grátis disponível — cortesia,
        entrada franca; junto com preco_min null significa evento grátis),
        esgotado (1 = sem ingressos disponíveis), popularidade (score de
        trending da fonte — quanto maior, mais em alta; null fora do Sympla),
        descricao (trecho inicial) e outras_urls (links do mesmo evento em
        outras plataformas, se houver). Para preço detalhado por lote ou a
        descrição completa de um evento, chame detalhar_evento com a url.
    """
    return consulta.buscar_eventos(
        texto=texto or None, cidade=cidade or None,
        data_inicio=data_inicio or None, data_fim=data_fim or None,
        bairro=bairro or None, tipo=tipo or None, gratis=gratis,
        limite=limite)


@mcp.tool()
@registrado
def detalhar_evento(url: str) -> dict:
    """Detalha UM evento da base: descrição completa (sem o corte da busca) e
    a tabela de lotes de ingresso. Use depois de buscar_eventos, com a url
    exata que ela devolveu, quando o usuário quiser aprofundar um evento —
    "me conta mais dessa festa", "quanto custa pra homem?", "tem cortesia?".

    Cada lote traz nome (cru, como a fonte publica), preco (R$ TOTAL a pagar,
    taxa já embutida), taxa (a parcela de taxa, quando a fonte separa), gratis
    (1 = cortesia/entrada franca) e esgotado (1 = lote sem estoque/encerrado).
    As condições do lote estão no NOME — "CORTESIA FEMININA DA COPA ATÉ 00H",
    "MASCULINO 2º LOTE", "meia-entrada" — leia-os para responder preço com
    precisão (ex.: "grátis para mulheres até 00h; masculino a partir de
    R$ 45 + 4,50 de taxa").

    Args:
        url: a url do evento, exatamente como veio de buscar_eventos.

    Returns:
        Dict único com os campos da busca + descricao completa + lotes
        (lista, na ordem de exibição da fonte), ou {"erro": ...} se a url
        não estiver na base.
    """
    return consulta.detalhar_evento(url)


@mcp.tool()
@registrado
def buscar_filmes(texto: str = "", data_inicio: str = "", data_fim: str = "",
                  cinema: str = "", limite: int = 20) -> list[dict]:
    """Filmes em cartaz nos cinemas de Brasília (Cinemark Iguatemi e Pier 21,
    Kinoplex ParkShopping/Pátio Brasil/Boulevard, Cinesystem CasaPark, Cine
    Brasília e Cine Cultura Liberty Mall). Use para responder o que está
    passando no cinema — "que filme tem em cartaz?", "tem animação pras
    crianças?", "o que estreia essa semana?". Todos os argumentos são opcionais;
    sessões que já começaram ficam de fora por padrão.

    Args:
        texto: termos de busca no título e gêneros (ex.: "animação",
            "terror OR suspense"). Vazio = todos em cartaz.
        data_inicio: início da janela, ISO 8601. Vazio = agora (só sessões
            futuras). Para "neste fim de semana", use a tool data_atual.
        data_fim: fim da janela, ISO 8601. Vazio = sem limite superior.
        cinema: filtra por cinema, nome parcial sem caixa (ex.: "pier",
            "casapark", "kinoplex"). Vazio = todos.
        limite: máximo de filmes (padrão 20).

    Returns:
        Lista de filmes ordenada por nº de sessões na janela (mais em cartaz
        primeiro): id, titulo, generos, duracao_min, classificacao,
        distribuidora, url, em_pre_venda (1 = ainda não estreou, só pré-venda),
        sessoes (contagem na janela), cinemas (onde está passando),
        primeira_sessao/ultima_sessao (ISO UTC). Para horários e preços de um
        filme, chame sessoes_filme com o id ou título.
    """
    return consulta.buscar_filmes(
        texto=texto or None, data_inicio=data_inicio or None,
        data_fim=data_fim or None, cinema=cinema or None, limite=limite)


@mcp.tool()
@registrado
def sessoes_filme(filme: str, data_inicio: str = "", data_fim: str = "",
                  cinema: str = "") -> dict:
    """Sessões de UM filme nos cinemas de Brasília: horário, cinema, sala,
    tipos e preço. Use depois de buscar_filmes, quando o usuário escolher um
    filme — "que horas tem Toy Story no Pier 21?", "quanto custa?", "tem 3D?".

    Os tipos da sessão vêm crus da fonte ("3D/XD/Dublado", "Vip/Legendado",
    "Cine Inclusivo/Dublado") — leia-os para responder com precisão (Dublado/
    Legendado/Nacional é o idioma; XD/Vip/D-Box são salas especiais; sessões
    temáticas como "Sessão Azul" ou "Cine Pets" aparecem aí também). Horários
    em ISO UTC — Brasília é UTC-3 (ex.: 21:10Z = 18:10 local).

    Args:
        filme: id ou título (parcial serve) devolvido por buscar_filmes.
        data_inicio: início da janela, ISO 8601. Vazio = agora.
        data_fim: fim da janela, ISO 8601. Vazio = sem limite.
        cinema: filtra por cinema, nome parcial sem caixa. Vazio = todos.

    Returns:
        Dict do filme (com poster e trailer) + sessoes: lista ordenada por
        horário com cinema, inicio (ISO UTC), sala, tipos, preco (R$; null =
        fonte não informou) e url_compra (checkout). {"erro": ...} se nenhum
        filme casar.
    """
    return consulta.sessoes_filme(
        filme, data_inicio=data_inicio or None, data_fim=data_fim or None,
        cinema=cinema or None)


@mcp.tool()
@registrado
def data_atual() -> dict:
    """Retorna a data/hora atual (UTC) e a janela do fim de semana corrente/próximo.
    Útil para montar filtros como "hoje", "neste fim de semana" ou "sexta que vem"
    antes de chamar buscar_eventos.
    """
    agora = datetime.now(timezone.utc)
    wd = agora.weekday()  # segunda=0 ... domingo=6
    # sexta do fim de semana corrente (se já é sex/sáb/dom) ou do próximo.
    desloc = -(wd - 4) if wd >= 4 else (4 - wd)
    sexta = (agora + timedelta(days=desloc)).replace(
        hour=18, minute=0, second=0, microsecond=0)
    domingo = (sexta + timedelta(days=2)).replace(
        hour=23, minute=59, second=59, microsecond=0)
    return {
        "agora": agora.isoformat(),
        "data": agora.date().isoformat(),
        "dia_semana": _DIAS_PT[wd],
        "fim_de_semana": {"inicio": sexta.isoformat(), "fim": domingo.isoformat()},
    }


if __name__ == "__main__":
    if "--http" in sys.argv:
        if MCP_RECURSO:
            # O caminho SAI da URL do recurso: se os dois divergissem, o
            # metadado anunciado apontaria para uma rota que não existe.
            caminho = urlparse(MCP_RECURSO).path or "/mcp"
        else:
            segredo = conexao.env_var("MCP_SEGREDO")
            if not segredo:
                sys.exit("Defina AUTHKIT_ISSUER + MCP_RECURSO (OAuth) ou "
                         "MCP_SEGREDO (prefixo secreto) para subir o HTTP.")
            caminho = f"/{segredo}/mcp"
        mcp.settings.stateless_http = True
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("PORT", "8000"))
        mcp.settings.streamable_http_path = caminho
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
