"""Probe determinístico: programação da semana dos cinemas-alvo de Brasília.

Fonte única: API de conteúdo da Ingresso.com (sem auth) —
GET /v0/sessions/city/{cityId}/theater/{theaterId}?date=YYYY-MM-DD

Cobre os 8 cinemas da lista do usuário (ver README.md). Gera:
- resumo legível no stdout (filme × cinema × dia × horários)
- capturas/semana.json com o agregado estruturado
- capturas/amostra_raw.json com UM payload bruto (referência de schema)

Uso: python spikes/cinema/probe_semana.py [--dias N]
"""

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = "https://api-content.ingresso.com/v0"
CIDADE_ID = "12"  # Brasília (Taguatinga seria 113)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

CINEMAS = {
    "847": "Cinemark Iguatemi",
    "128": "Cinemark Pier 21",
    "124": "Kinoplex ParkShopping",
    "126": "Kinoplex Pátio Brasil",
    "833": "Kinoplex Boulevard",
    "1605": "Cinesystem CasaPark",  # nome oficial: "Cinesystem Caixa Brasília"
    "1583": "Cine Brasília",
    "1538": "Cine Cultura Liberty Mall",
}

AQUI = Path(__file__).parent
CAPTURAS = AQUI / "capturas"


def sessoes_do_dia(teatro_id: str, dia: str) -> list[dict]:
    """Devolve a lista de blocos-dia da API (normalmente 1 item) para o cinema."""
    url = f"{BASE}/sessions/city/{CIDADE_ID}/theater/{teatro_id}"
    r = requests.get(url, params={"date": dia}, headers=UA, timeout=30)
    if r.status_code == 404:  # a API devolve 404 p/ dia sem sessão (não é erro)
        return []
    r.raise_for_status()
    dados = r.json()
    return dados if isinstance(dados, list) else []


def coletar(dias: int) -> tuple[dict, dict | None]:
    """Varre cinemas × dias. Devolve (agregado, amostra_raw)."""
    hoje = date.today()
    datas = [(hoje + timedelta(days=n)).isoformat() for n in range(dias)]
    agregado: dict = {}  # titulo -> {"meta": {...}, "sessoes": [...]}
    amostra_raw = None
    erros = []

    for teatro_id, apelido in CINEMAS.items():
        for dia in datas:
            try:
                blocos = sessoes_do_dia(teatro_id, dia)
            except requests.RequestException as e:
                erros.append(f"{apelido} {dia}: {e}")
                continue
            if amostra_raw is None and blocos:
                amostra_raw = blocos
            for bloco in blocos:
                for filme in bloco.get("movies", []):
                    titulo = filme.get("title") or "?"
                    reg = agregado.setdefault(titulo, {
                        "meta": {
                            "generos": filme.get("genres") or [],
                            "duracao_min": filme.get("duration"),
                            "classificacao": filme.get("contentRating"),
                            "distribuidora": filme.get("distributor"),
                            "url": filme.get("siteURL"),
                        },
                        "sessoes": [],
                    })
                    for sala in filme.get("rooms", []):
                        for s in sala.get("sessions", []):
                            tipos = [t["name"] for t in s.get("types", [])
                                     if t.get("display")] or ["2D"]
                            reg["sessoes"].append({
                                "cinema": apelido,
                                "dia": dia,
                                "hora": s.get("time"),
                                "sala": s.get("room"),
                                "tipo": "/".join(tipos),
                                "preco": s.get("price"),
                                "compra": s.get("siteURL"),
                            })
            time.sleep(0.3)  # educação com a API
        print(f"  ok {apelido}", file=sys.stderr)

    if erros:
        print("ERROS:\n  " + "\n  ".join(erros), file=sys.stderr)
    return agregado, amostra_raw


def resumo(agregado: dict, dias: int) -> str:
    linhas = [f"== {len(agregado)} filmes em cartaz nos {len(CINEMAS)} cinemas "
              f"(próximos {dias} dias) =="]
    por_qtd = sorted(agregado.items(), key=lambda kv: -len(kv[1]["sessoes"]))
    for titulo, reg in por_qtd:
        m = reg["meta"]
        cinemas = sorted({s["cinema"] for s in reg["sessoes"]})
        linhas.append(
            f"\n{titulo}  [{', '.join(m['generos'])}] "
            f"{m['duracao_min']}min {m['classificacao']} — "
            f"{len(reg['sessoes'])} sessões em {len(cinemas)} cinema(s)"
        )
        for cine in cinemas:
            do_cine = [s for s in reg["sessoes"] if s["cinema"] == cine]
            por_dia: dict = {}
            for s in do_cine:
                por_dia.setdefault(s["dia"][5:], []).append(f"{s['hora']} {s['tipo']}")
            dias_txt = "; ".join(f"{d} → {', '.join(sorted(hs))}"
                                 for d, hs in sorted(por_dia.items()))
            linhas.append(f"  {cine}: {dias_txt}")
    return "\n".join(linhas)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=7)
    args = ap.parse_args()

    agregado, amostra = coletar(args.dias)

    CAPTURAS.mkdir(exist_ok=True)
    (CAPTURAS / "semana.json").write_text(
        json.dumps(agregado, ensure_ascii=False, indent=2), encoding="utf-8")
    if amostra:
        (CAPTURAS / "amostra_raw.json").write_text(
            json.dumps(amostra, ensure_ascii=False, indent=2), encoding="utf-8")

    print(resumo(agregado, args.dias))
    total = sum(len(r["sessoes"]) for r in agregado.values())
    print(f"\nTotal: {total} sessões. Agregado em capturas/semana.json")
