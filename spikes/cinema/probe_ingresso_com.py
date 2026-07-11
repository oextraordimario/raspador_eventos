"""Sondagem da API de conteúdo da Ingresso.com (agregador de cinemas).

Hipótese: api-content.ingresso.com expõe, sem auth, os cinemas e as sessões
por cidade — cobrindo várias redes de uma vez (Kinoplex, Cinépolis, ...).

Passo 1 (este script): descobrir o cityId de Brasília e listar os cinemas.
Uso: python spikes/cinema/probe_ingresso_com.py
"""

import json
import sys

import requests

BASE = "https://api-content.ingresso.com/v0"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def get(path: str):
    r = requests.get(f"{BASE}{path}", headers=UA, timeout=30)
    print(f"GET {path} -> {r.status_code}", file=sys.stderr)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    df = get("/states/DF")
    cidades = df.get("cities", [])
    print(json.dumps(
        [{"id": c.get("id"), "nome": c.get("name")} for c in cidades],
        ensure_ascii=False, indent=2,
    ))

    bsb = next((c for c in cidades if "bras" in c.get("name", "").lower()), None)
    if not bsb:
        sys.exit("Brasília não encontrada em /states/DF")

    teatros = get(f"/theaters/city/{bsb['id']}")
    # a API pagina alguns recursos como {"items": [...]}; aceita os dois formatos
    items = teatros.get("items", teatros) if isinstance(teatros, dict) else teatros
    print(json.dumps(
        [{"id": t.get("id"), "nome": t.get("name"), "rede": t.get("corporation")}
         for t in items],
        ensure_ascii=False, indent=2,
    ))
