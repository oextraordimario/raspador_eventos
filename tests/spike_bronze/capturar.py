"""Passo 1 do spike NI-14 (camada Bronze): captura os payloads brutos.

Não toca em src/ nem na base: intercepta o _normalizar de cada scraper
(monkeypatch) durante uma raspagem normal e grava o payload de entrada em JSONL
nesta pasta. Também captura, por amostra, o payload de detalhe (BFF do Sympla e
GET /events/{slug} do Ingresse) — o JSON-LD do Shotgun já é o detalhe.

No Sympla, a produção pede à API só os campos que usa (parâmetro `only`); aqui
o `only` é removido para capturar o payload completo, permitindo distinguir
"descartado pelo _normalizar" de "nem solicitado".

Uso (da raiz do repo):
    python -X utf8 tests/spike_bronze/capturar.py
    python -X utf8 tests/spike_bronze/capturar.py --sem-shotgun
"""

import json
import re
import sys
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA.parent.parent / "src"))

from scrapers import ingresse, shotgun, sympla  # noqa: E402

AMOSTRA_DETALHE = 30  # eventos por fonte para capturar o payload de detalhe
PAUSA_DETALHE = 0.4   # mesmo ritmo do passo "descrever" do atualizar.py


def _salvar_jsonl(nome, registros):
    caminho = PASTA / nome
    with caminho.open("w", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    kb = caminho.stat().st_size / 1024
    print(f"  -> {nome}: {len(registros)} payloads, {kb:,.0f} KB")


def _interceptar_normalizar(modulo, capturados):
    """Troca o _normalizar do módulo por um wrapper que guarda o payload bruto."""
    original = modulo._normalizar

    def wrapper(payload, *args, **kw):
        norm = original(payload, *args, **kw)
        capturados[norm["id"]] = payload
        return norm

    modulo._normalizar = wrapper


def capturar_sympla():
    caps = {}
    _interceptar_normalizar(sympla, caps)

    # remove o `only` para a API devolver o payload completo
    get_original = sympla._get
    sympla._get = lambda params: get_original(
        {k: v for k, v in params.items() if k != "only"})

    print("\n[sympla] raspando catálogo (payload completo, sem `only`)...")
    eventos = sympla.raspar(city="brasilia", state="DF", location="Brasília",
                            max_paginas=10)
    _salvar_jsonl("sympla_catalogo.jsonl",
                  [{"id": i, "payload": p} for i, p in caps.items()])

    print(f"[sympla] detalhe (BFF da página), amostra de {AMOSTRA_DETALHE}...")
    detalhes = []
    for e in eventos[:AMOSTRA_DETALHE]:
        m = re.search(r"/(\d+)/?$", e.get("url") or "")
        if not m:
            continue
        try:
            payload = sympla._get_url(f"{sympla.BFF_EVENTO}{m.group(1)}")
        except Exception as ex:
            print(f"  falha em {e['id']}: {type(ex).__name__}")
            continue
        detalhes.append({"id": e["id"], "payload": payload})
        time.sleep(PAUSA_DETALHE)
    _salvar_jsonl("sympla_evento.jsonl", detalhes)
    return {"catalogo": len(caps), "detalhe": len(detalhes)}


def capturar_ingresse():
    caps = {}
    _interceptar_normalizar(ingresse, caps)

    print("\n[ingresse] raspando catálogo...")
    eventos = ingresse.raspar()
    _salvar_jsonl("ingresse_catalogo.jsonl",
                  [{"id": i, "payload": p} for i, p in caps.items()])

    print(f"[ingresse] detalhe (GET /events/{{slug}}), amostra de {AMOSTRA_DETALHE}...")
    detalhes = []
    for e in eventos[:AMOSTRA_DETALHE]:
        if not e.get("url"):
            continue
        slug = e["url"].rstrip("/").rsplit("/", 1)[-1]
        try:
            payload = ingresse._get_url(
                f"{ingresse.API_EVENTO}{urllib.parse.quote(slug)}")
        except Exception as ex:
            print(f"  falha em {e['id']}: {type(ex).__name__}")
            continue
        detalhes.append({"id": e["id"], "payload": payload})
        time.sleep(PAUSA_DETALHE)
    _salvar_jsonl("ingresse_evento.jsonl", detalhes)
    return {"catalogo": len(caps), "detalhe": len(detalhes)}


def capturar_shotgun():
    caps = {}
    _interceptar_normalizar(shotgun, caps)

    print("\n[shotgun] raspando (Playwright — o JSON-LD já é o detalhe)...")
    shotgun.raspar(city_slug="brasilia")
    _salvar_jsonl("shotgun_jsonld.jsonl",
                  [{"id": i, "payload": p} for i, p in caps.items()])
    return {"catalogo": len(caps)}


def main():
    incluir_shotgun = "--sem-shotgun" not in sys.argv
    meta = {"quando": datetime.now(timezone.utc).isoformat(), "fontes": {}}

    tarefas = [("sympla", capturar_sympla), ("ingresse", capturar_ingresse)]
    if incluir_shotgun:
        tarefas.append(("shotgun", capturar_shotgun))

    for nome, fn in tarefas:
        try:
            meta["fontes"][nome] = fn()
        except Exception as e:
            traceback.print_exc()
            meta["fontes"][nome] = {"erro": f"{type(e).__name__}: {e}"}
            print(f"[{nome}] FALHOU — seguindo com as outras fontes.")

    (PASTA / "captura_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nCaptura concluída: {meta['fontes']}")


if __name__ == "__main__":
    main()
