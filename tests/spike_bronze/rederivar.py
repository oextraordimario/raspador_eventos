"""Passo 4 do spike NI-14: re-derivação a seco (a promessa do Bronze).

Extrai, SÓ dos JSONL capturados (zero requisições novas), campos que o schema
não tem hoje, e mede contra a base (somente leitura) quantos eventos ganhariam
valor. Prova que, com o bruto guardado, "campo novo" não exige re-raspar.

Campos derivados (escolhidos da saída do analisar.py):
- sympla:   bairro (location.neighborhood) e popularidade (global_score)
- ingresse: nº de sessões (sessions[] do detalhe — evento multi-dia tem várias;
            a base guarda só uma data)
- shotgun:  esgotado (todas as offers SoldOut), cancelado (eventStatus) e
            hora de abertura (doorTime)

Saída: relatório no stdout + rederivacao.json nesta pasta. Não escreve na base.

Uso (da raiz do repo):
    python -X utf8 tests/spike_bronze/rederivar.py
"""

import json
import sqlite3
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
DB = PASTA.parent.parent / "data" / "eventos.db"


def _ler(nome):
    caminho = PASTA / nome
    if not caminho.exists():
        return {}
    return {json.loads(l)["id"]: json.loads(l)["payload"]
            for l in caminho.read_text(encoding="utf-8").split("\n") if l.strip()}


def derivar():
    derivados = {}  # id -> {campo: valor}

    for id_, p in _ler("sympla_catalogo.jsonl").items():
        loc = p.get("location") or {}
        d = {}
        if (loc.get("neighborhood") or "").strip():
            d["bairro"] = loc["neighborhood"].strip()
        if p.get("global_score") is not None:
            d["popularidade"] = p["global_score"]
        if d:
            derivados[id_] = d

    for id_, p in _ler("ingresse_evento.jsonl").items():
        sessoes = p.get("sessions") or []
        if sessoes:
            derivados[id_] = {"n_sessoes": len(sessoes)}

    for id_, p in _ler("shotgun_jsonld.jsonl").items():
        offers = p.get("offers") or []
        offers = offers if isinstance(offers, list) else [offers]
        disp = [o.get("availability", "") for o in offers if isinstance(o, dict)]
        d = {}
        if disp:
            d["esgotado"] = all(a.endswith("SoldOut") for a in disp)
        status = p.get("eventStatus") or ""
        d["cancelado"] = not status.endswith("EventScheduled") if status else None
        if p.get("doorTime"):
            d["abre_as"] = p["doorTime"]
        derivados[id_] = {k: v for k, v in d.items() if v is not None}
    return derivados


def main():
    derivados = derivar()
    if not derivados:
        sys.exit("Nenhum JSONL encontrado — rode capturar.py antes.")

    na_base = set()
    if DB.exists():
        con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
        na_base = {r[0] for r in con.execute("SELECT id FROM eventos")}
        con.close()

    contagem = {}
    for id_, campos in derivados.items():
        for campo in campos:
            contagem.setdefault(campo, {"derivados": 0, "na_base": 0})
            contagem[campo]["derivados"] += 1
            if id_ in na_base:
                contagem[campo]["na_base"] += 1

    print("=" * 72)
    print("PASSO 4 — re-derivação a seco (zero requisições; base intocada)")
    print("=" * 72)
    print(f"\n  {len(derivados)} eventos ganharam pelo menos 1 campo novo, "
          f"derivado só do bruto capturado:")
    for campo, c in sorted(contagem.items(), key=lambda kv: -kv[1]["derivados"]):
        print(f"  {campo:<14} {c['derivados']:>4} eventos derivados "
              f"({c['na_base']} presentes na base atual ganhariam o valor)")

    exemplos = dict(list(derivados.items())[:3])
    print("\n  amostra:")
    for id_, campos in exemplos.items():
        print(f"    {id_}: {json.dumps(campos, ensure_ascii=False)[:90]}")

    (PASTA / "rederivacao.json").write_text(
        json.dumps({"contagem": contagem, "derivados": derivados},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalhe salvo em {PASTA / 'rederivacao.json'}")


if __name__ == "__main__":
    main()
