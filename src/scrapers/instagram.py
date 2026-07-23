"""Raspador de contexto/eventos do Instagram via Monid (endpoints TikHub).

Muita casa de Brasília divulga a agenda SÓ no Instagram (Culto, Ordinário) —
ingresso na porta, sem página de venda. Este módulo puxa posts e stories dos
perfis da watchlist (dados/perfis_instagram.yaml, NI-24) pela API paga do
Monid (CLI `monid`, revenda dos endpoints TikHub), que devolve o payload
interno do Instagram em JSON — sem navegador e sem lidar com login wall
(desriscado no spike spikes/instagram-monid/). A chave de API mora no config
do próprio monid (`monid keys add`), NUNCA neste repo — por isso o binário é
chamado via subprocess em vez de HTTP direto.

Contrato próprio (como o cinema — devolve o bruto, não lista de eventos):
raspar(perfis) → {"raw": [(perfil, code, origem, payload)], "erros": [...]}.
Quem grava é store.gravar_instagram_raw; quem transforma post em evento
(fonte='instagram') é derivar.aplicar_instagram, a partir do post + da
extração do flyer (extrair(), abaixo — visão multimodal via `claude -p`,
decisão do PRD §7: subagente na assinatura, não API paga).

Custo por CALL (não por resultado): posts $0,003 + stories $0,003 por perfil
por rodada. A extração roda 1x por post (nunca re-extrai shortcode) e não
custa dinheiro. Spec: docs/specs/20260723_instagram-como-fonte/.
"""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import yaml

_RAIZ = Path(__file__).resolve().parent.parent.parent
WATCHLIST = _RAIZ / "dados" / "perfis_instagram.yaml"
MIDIAS = _RAIZ / "midias" / "instagram"   # flyers baixados (gitignorado)

MONID = shutil.which("monid") or "monid"
CLAUDE = shutil.which("claude") or "claude"
PROVIDER = "tikhub"
EP_POSTS = "/api/v1/instagram/v2/fetch_user_posts"
EP_STORIES = "/api/v1/instagram/v2/fetch_user_stories"
TERMINAIS = {"COMPLETED", "FAILED", "BLOCKED", "STOPPED", "TIME_OUT"}
UA = {"User-Agent": "Mozilla/5.0"}

# O que o subagente de visão devolve por post. O flyer estiliza e mente
# (achado do spike): a legenda entra na MESMA chamada para validar, e quem
# decide se o resultado vira evento é a guarda de derivar.aplicar_instagram
# (e_evento + confianca alta + data futura) — não este prompt.
PROMPT_EXTRACAO = """Você extrai dados de divulgações de eventos do Instagram de casas noturnas de Brasília.

{instrucao_imagem}

Legenda do post:
---
{legenda}
---

Responda SOMENTE com um JSON (sem markdown, sem comentários) no formato:
{{"e_evento": true/false, "confianca": "alta"/"media"/"baixa",
  "nome": "nome do evento ou null", "data": "DD/MM ou DD/MM/AAAA ou null",
  "hora": "HH:MM ou null", "preco": numero em reais ou null,
  "lineup": ["atração", ...] ou null, "local": "local se citado ou null",
  "observacoes": "condições relevantes (ex.: entrada grátis até 22h) ou null"}}

Regras:
- e_evento=true SÓ para divulgação de UM evento datado (festa/show/balada).
  Retrospectiva ("foi incrível"), meme, aviso de funcionamento e agenda de
  vários eventos de uma vez NÃO são (e_evento=false).
- confianca "alta" só quando nome E data estão legíveis sem ambiguidade.
- preco é o menor valor de ENTRADA anunciado (couvert/ingresso), não consumo.
- Não invente: campo ausente na imagem e na legenda = null."""


# ── watchlist (NI-24) ───────────────────────────────────────────────────────

def carregar_watchlist(caminho=None):
    """Lê a watchlist YAML → lista de dicts com defaults preenchidos.

    Arquivo ausente devolve [] (o passo do Instagram vira no-op — instalação
    sem a fonte segue funcionando).
    """
    arq = Path(caminho) if caminho else WATCHLIST
    if not arq.exists():
        return []
    perfis = yaml.safe_load(arq.read_text(encoding="utf-8")) or []
    for p in perfis:
        p.setdefault("tipo", "casa")
        p.setdefault("ativo", True)
        p.setdefault("local_aliases", [])
        p.setdefault("nome", p.get("usuario"))
    return perfis


def watchlist_ativos(caminho=None):
    return [p for p in carregar_watchlist(caminho) if p.get("ativo")]


def aliases_local(caminho=None):
    """{alias: nome canônico} das casas da watchlist, para o dedupe conciliar
    o local do post ("Culto Rock Bar") com a grafia da plataforma ("Culto").
    O próprio nome canônico entra no mapa (alias de si mesmo)."""
    m = {}
    for p in carregar_watchlist(caminho):
        m[p["nome"]] = p["nome"]
        for alias in p.get("local_aliases") or []:
            m[alias] = p["nome"]
    return m


# ── CLI monid (fire-and-poll, herdado do probe do spike) ────────────────────

def _monid(*args):
    r = subprocess.run([MONID, *args], capture_output=True, text=True,
                       encoding="utf-8")
    return (r.stdout or "") + (r.stderr or "")


def _rodar(endpoint, query, timeout=180, pausa_poll=5):
    """Dispara um run no monid e aguarda o estado terminal; devolve o JSON."""
    out = _monid("run", "-p", PROVIDER, "-e", endpoint,
                 "--query", json.dumps(query))
    run_id = next((w for w in out.split()
                   if w.startswith("01") and len(w) >= 24), None)
    if not run_id:
        raise RuntimeError(f"monid não devolveu runId: {out[:300]}")
    prazo = time.monotonic() + timeout
    while time.monotonic() < prazo:
        got = _monid("runs", "get", "-r", run_id, "--json")
        try:
            payload = json.loads(got[got.index("{"): got.rindex("}") + 1])
        except ValueError:
            time.sleep(pausa_poll)
            continue
        status = payload.get("status") or payload.get("run", {}).get("status")
        if status in TERMINAIS:
            if status != "COMPLETED":
                raise RuntimeError(f"run monid {run_id} terminou em {status}")
            return payload.get("output") or payload.get("result") or payload
        time.sleep(pausa_poll)
    raise TimeoutError(f"run monid {run_id} não terminou em {timeout}s")


# ── raspagem ────────────────────────────────────────────────────────────────

# Estatísticas da última chamada a raspar(), para o relatório de cobertura
# (coletados = perfis cujos POSTS responderam; stories falhando sozinho não
# derruba o perfil — é dado perecível, a próxima rodada re-tenta).
ULTIMA_RASPAGEM = {}


def raspar(perfis):
    """Posts + stories ativos de cada perfil da watchlist (1 página de cada —
    ~12 posts; a Bronze acumula rodada a rodada, decisão da spec §3.6).

    Retorna {"raw": [(perfil, code, origem, payload)], "erros": [{perfil,
    erro}]}. Perfil que falhou fica fora de raw e não derruba os demais.
    """
    raw, erros = [], []
    responderam = set()
    for p in perfis:
        usuario = p["usuario"]
        print(f"  @{usuario}...", end=" ", flush=True)
        try:
            posts = _rodar(EP_POSTS, {"username": usuario})
            itens = (posts.get("data") or {}).get("items") or []
            for item in itens:
                if item.get("code"):
                    raw.append((usuario, item["code"], "post", item))
            responderam.add(usuario)
            print(f"{len(itens)} posts", end="")
        except Exception as e:
            erros.append({"perfil": usuario,
                          "erro": f"posts: {type(e).__name__}: {e}"})
            print("posts FALHARAM")
            continue
        try:
            stories = _rodar(EP_STORIES, {"username": usuario})
            st = (stories.get("data") or {}).get("items") or []
            for item in st:
                if item.get("code"):
                    raw.append((usuario, item["code"], "story", item))
            print(f", {len(st)} stories")
        except Exception as e:
            erros.append({"perfil": usuario,
                          "erro": f"stories: {type(e).__name__}: {e}"})
            print(", stories FALHARAM")
    ULTIMA_RASPAGEM.update(coletados=len(responderam), total_site=len(perfis))
    return {"raw": raw, "erros": erros}


def url_imagem(post):
    """Maior imagem do post (1080px vem primeiro em image_versions.items).
    Em vídeo, image_versions é o poster — serve como flyer parado."""
    iv = post.get("image_versions") or {}
    cands = iv.get("items") or iv.get("candidates") or []
    if not cands and (post.get("carousel_media") or []):
        return url_imagem(post["carousel_media"][0])  # carrossel: 1ª mídia
    return cands[0].get("url") if cands else post.get("thumbnail_url")


def baixar_midia(post, dest=None):
    """Baixa a imagem do post (as URLs do CDN expiram em horas — chamar logo
    após a raspagem). Devolve o Path ou None se o post não tem imagem."""
    url = url_imagem(post)
    if not url:
        return None
    dest = Path(dest) if dest else MIDIAS / f"{post['code']}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dados = urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=90).read()
    dest.write_bytes(dados)
    return dest


# ── extração do flyer (NI-26) ───────────────────────────────────────────────

def extrair(legenda, imagem=None, timeout=300):
    """Lê legenda + flyer com o subagente de visão e devolve o dict extraído.

    `claude -p` headless com Sonnet (PRD §7: assinatura, não API paga); a
    imagem entra via tool Read (única permitida). Sem imagem (post sem mídia
    ou download falhou), extrai só da legenda — melhor que perder o post.
    Erros sobem: o chamador registra e re-tenta na próxima rodada (fila
    natural: shortcode sem origem='extracao' na Bronze).
    """
    if imagem:
        instrucao = (f"Leia a imagem do flyer em {Path(imagem).as_posix()} "
                     "(tool Read) e cruze com a legenda abaixo.")
    else:
        instrucao = ("Não há imagem disponível — extraia apenas da legenda "
                     "abaixo.")
    prompt = PROMPT_EXTRACAO.format(instrucao_imagem=instrucao,
                                    legenda=(legenda or "").strip() or "(sem legenda)")
    args = [CLAUDE, "-p", prompt, "--model", "sonnet",
            "--output-format", "json", "--allowedTools", "Read"]
    # Decisão do PRD §7: a extração roda na ASSINATURA (login claude.ai), não
    # em API paga. Chave de API no ambiente tem precedência no CLI e furaria a
    # decisão (ou falha, se a key não tem crédito) — sai do env do subprocesso.
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p saiu com {r.returncode}: "
                           f"{(r.stderr or r.stdout or '')[:300]}")
    envelope = json.loads(r.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude -p com erro: "
                           f"{str(envelope.get('result'))[:300]}")
    texto = envelope.get("result") or ""
    try:
        ext = json.loads(texto[texto.index("{"): texto.rindex("}") + 1])
    except ValueError:
        raise RuntimeError(f"extração não devolveu JSON: {texto[:300]}")
    if "e_evento" not in ext:
        raise RuntimeError(f"extração sem o campo e_evento: {texto[:300]}")
    return ext


def legenda_do_post(post):
    cap = post.get("caption") or {}
    return cap.get("text") if isinstance(cap, dict) else None


# Sem hora no flyer/legenda o evento fica com data pura (00:00 local,
# precedente Ticket and Go: "só a data já serve ao filtro por dia").
_RE_DATA = re.compile(r"(\d{1,2})\s*[/.]\s*(\d{1,2})(?:\s*[/.]\s*(\d{2,4}))?")
_RE_HORA = re.compile(r"(\d{1,2})[:h](\d{2})?", re.IGNORECASE)


# Distância máxima pro ANO INFERIDO (sem ano no flyer): rolar "21/07" visto
# num post de 22/07 para o ano seguinte criaria um evento fantasma a ~364
# dias — data recém-passada é retrospectiva, não anúncio. Casas não anunciam
# com mais de ~9 meses; acima disso a inferência é descartada.
INFERENCIA_MAX_DIAS = 270


def montar_start_date(ext, taken_at):
    """Data extraída ("25/07", com hora opcional) → ISO local -03:00, com o
    ano inferido: a PRÓXIMA ocorrência a partir da data LOCAL do post (post
    de julho falando de 25/7 = este ano; de dezembro falando de 5/1 = ano que
    vem — mas nunca a mais de INFERENCIA_MAX_DIAS). Ano explícito no flyer
    vence. Devolve None se não há data válida (a guarda da derivação descarta
    o post).
    """
    from datetime import date, datetime, timedelta, timezone
    m = _RE_DATA.search(str(ext.get("data") or ""))
    if not m or not taken_at:
        return None
    dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
    # data do post no fuso de Brasília: post das 23h anunciando festa "de
    # hoje" ainda é hoje (em UTC já seria amanhã e a data rolaria um ano)
    fuso_bsb = timezone(timedelta(hours=-3))
    post_dia = datetime.fromtimestamp(int(taken_at), tz=fuso_bsb).date()
    try:
        if ano:
            alvo = date(int(ano) + (2000 if int(ano) < 100 else 0), mes, dia)
            if alvo < post_dia:
                return None  # ano explícito no passado = retrospectiva
        else:
            alvo = date(post_dia.year, mes, dia)
            if alvo < post_dia:
                alvo = date(post_dia.year + 1, mes, dia)
            if (alvo - post_dia).days > INFERENCIA_MAX_DIAS:
                return None  # provável retrospectiva ("ontem 21/07")
    except ValueError:
        return None  # 31/02 etc. — extração ruim não vira evento
    h = _RE_HORA.search(str(ext.get("hora") or ""))
    hora, minuto = (int(h.group(1)), int(h.group(2) or 0)) if h else (0, 0)
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        hora = minuto = 0
    return f"{alvo.isoformat()}T{hora:02d}:{minuto:02d}:00-03:00"
