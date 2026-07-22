"""Probe: puxar contexto de eventos do Instagram via Monid CLI (endpoints TikHub).

Backlog NI-06 ("Instagram como fonte de contexto"). A dor mapeada no backlog era
login wall / bloqueios / layout volátil da raspagem direta do Instagram. Este spike
testa contornar isso por uma **API paga intermediária** (Monid → provider TikHub),
que devolve o payload interno do Instagram em JSON, sem navegador e sem lidar com o
bloqueio nós mesmos.

Descoberta (2026-07-21): o Monid é um CLI (`npm i -g @monid-ai/cli`) que descobre e
executa centenas de endpoints. Fluxo: discover → inspect → run → poll. A chave de API
mora no config do próprio monid (`monid keys add`), NÃO neste repo — por isso o probe
chama o binário `monid` em vez de bater HTTP direto (não há segredo aqui dentro).

Endpoints TikHub usados (preço por CALL, não por resultado — janela inteira num run):
  /api/v1/instagram/v2/fetch_user_posts   $0.003  posts do perfil (paginado)
  /api/v1/instagram/v2/fetch_user_stories $0.003  stories ativos (somem em 24h)
  /api/v1/instagram/v1/fetch_post_by_url  $0.0015 detalhe de 1 post (schema GraphQL web)
  /api/v1/instagram/v2/fetch_post_comments $0.003 comentários de 1 post
Todos usam QUERY PARAMS (username / post_url / code_or_url), nunca o corpo.

Achados completos: ver README.md deste diretório.

Gera (em capturas/, gitignored — payloads brutos, regeneráveis):
  user_posts_full.json   catálogo cru de posts do @
  stories.json           stories ativos crus
  midias/                imagens dos posts + poster e vídeo de story de amostra

Pegadinhas (2026-07-21, Windows):
  - No **Git Bash**, o monid recebe o endpoint `/api/...` convertido em caminho do
    Windows; rode com `MSYS_NO_PATHCONV=1` na frente. Chamando via subprocess (como
    aqui) NÃO passa pelo bash, então não há conversão.
  - No **PowerShell 5.1**, `--query '{...}'` come as aspas do JSON. Aqui passamos a
    query como item de lista (subprocess, shell=False), o que preserva as aspas.
  - `monid runs get -o <arq>` não gravou nada nos testes; use `--json` no stdout.

Uso: python spikes/instagram-monid/probe_monid_instagram.py --user cultorockbar
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

AQUI = Path(__file__).parent
CAP = AQUI / "capturas"
MID = CAP / "midias"
MONID = shutil.which("monid") or "monid"
PROV = "tikhub"
TERMINAIS = {"COMPLETED", "FAILED", "BLOCKED", "STOPPED", "TIME_OUT"}
UA = {"User-Agent": "Mozilla/5.0"}


def _monid(*args):
    """Roda o CLI monid e devolve stdout (texto)."""
    r = subprocess.run([MONID, *args], capture_output=True, text=True, encoding="utf-8")
    return (r.stdout or "") + (r.stderr or "")


def rodar(endpoint, query, timeout=180):
    """Fire-and-poll: dispara um run, aguarda estado terminal, devolve o JSON de saída."""
    out = _monid("run", "-p", PROV, "-e", endpoint, "--query", json.dumps(query))
    run_id = next((w for w in out.split() if w.startswith("01") and len(w) >= 24), None)
    if not run_id:
        raise RuntimeError(f"não achei runId na saída:\n{out}")
    prazo = time.monotonic() + timeout
    while time.monotonic() < prazo:
        got = _monid("runs", "get", "-r", run_id, "--json")
        try:
            payload = json.loads(got[got.index("{"): got.rindex("}") + 1])
        except ValueError:
            time.sleep(5)
            continue
        status = payload.get("status") or payload.get("run", {}).get("status")
        if status in TERMINAIS:
            if status != "COMPLETED":
                raise RuntimeError(f"run {run_id} terminou em {status}")
            # o corpo do provider fica em .output / .result dependendo da versão
            return payload.get("output") or payload.get("result") or payload
        time.sleep(5)
    raise TimeoutError(f"run {run_id} não terminou em {timeout}s")


def baixar(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
    dest.write_bytes(data)
    return len(data)


def maior_imagem(item):
    iv = item.get("image_versions") or {}
    cands = iv.get("items") or iv.get("candidates") or []
    return cands[0]["url"] if cands else item.get("thumbnail_url")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="cultorockbar", help="username do Instagram")
    ap.add_argument("--sem-midia", action="store_true", help="não baixar imagens/vídeos")
    args = ap.parse_args()
    CAP.mkdir(parents=True, exist_ok=True)

    print(f"→ posts de @{args.user} ...")
    posts = rodar("/api/v1/instagram/v2/fetch_user_posts", {"username": args.user})
    (CAP / "user_posts_full.json").write_text(
        json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    itens = posts["data"]["items"]
    print(f"  {len(itens)} posts salvos em capturas/user_posts_full.json")

    print(f"→ stories de @{args.user} ...")
    stories = rodar("/api/v1/instagram/v2/fetch_user_stories", {"username": args.user})
    (CAP / "stories.json").write_text(
        json.dumps(stories, ensure_ascii=False, indent=2), encoding="utf-8")
    st_itens = stories.get("data", {}).get("items", [])
    print(f"  {len(st_itens)} stories ativos salvos em capturas/stories.json")

    if not args.sem_midia:
        print("→ baixando mídias de amostra ...")
        for p in itens[:4]:
            url = maior_imagem(p)
            if url:
                n = baixar(url, MID / f"post_{p['code']}.jpg")
                print(f"  post_{p['code']}.jpg -> {n} bytes")
        if st_itens:
            s = st_itens[0]
            if maior_imagem(s):
                baixar(maior_imagem(s), MID / "story0_poster.jpg")
            vv = s.get("video_versions") or []
            if vv:
                baixar(vv[0]["url"], MID / "story0_video.mp4")
            print("  poster/vídeo do primeiro story salvos em capturas/midias/")

    print("\nOK. Achados em spikes/instagram-monid/README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
