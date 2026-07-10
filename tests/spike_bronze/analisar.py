"""Passos 2 e 3 do spike NI-14: custo do bruto + desperdício de campos.

Offline: lê os JSONL gerados por capturar.py (nesta pasta) e a base
data/eventos.db (somente leitura, se existir).

- Passo 2 (custo): bytes por evento e projeção do peso de uma camada Bronze.
- Passo 3 (desperdício): campos presentes no payload que o _normalizar de cada
  scraper NÃO mapeia, ranqueados por taxa de preenchimento. No catálogo do
  Sympla, marca também se o campo é sequer solicitado em produção (`only`).

Saída: relatório no stdout + analise.json nesta pasta.

Uso (da raiz do repo):
    python -X utf8 tests/spike_bronze/analisar.py
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent.parent
DB = RAIZ / "data" / "eventos.db"

# Campos que o _normalizar (e funções auxiliares) de cada scraper JÁ consome —
# tudo fora destas listas é descartado hoje. Mantido em sincronia manual com
# src/scrapers/*.py (spike: leitura de 2026-07-10).
MAPEADOS = {
    "sympla_catalogo.jsonl": {
        "id", "name", "start_date", "end_date", "url", "event_type",
        "location.city", "location.state", "location.name", "location.address",
        "location.lat", "location.lon", "organizer.name",
        "images.lg", "images.original",
    },
    "sympla_evento.jsonl": {  # raspar_descricao: detail/strippedDetail/eventsCategory
        "detail", "strippedDetail", "eventsCategory", "eventsCategory.name",
    },
    "ingresse_catalogo.jsonl": {
        "id", "title", "slug", "event_date", "session.dateTime",
        "place.city", "place.state", "place.name", "place.street",
        "place.location.lat", "place.location.lon",
        "poster.large", "poster.medium", "images.large", "images.medium",
    },
    "ingresse_evento.jsonl": {"description"},
    "shotgun_jsonld.jsonl": {
        "name", "startDate", "endDate", "url", "image", "description",
        "location.name", "location.address.addressLocality",
        "location.address.streetAddress",
        "location.geo.latitude", "location.geo.longitude",
        "organizer.name", "performer[].name",
        "offers[].lowPrice", "offers[].price",
    },
}

# Raízes que a produção pede à API do Sympla (parâmetro `only` em sympla.CAMPOS);
# campo fora disto nem chega em produção — só apareceu porque a captura tira o `only`.
SOLICITADO_SYMPLA = {"name", "start_date", "end_date", "images", "event_type",
                     "location", "id", "url", "organizer", "type"}

PRECO_RE = re.compile(r"price|preco|valor|amount|cost|fee|ticket|batch|lote|sold",
                      re.I)


def _achatar(obj, prefixo=""):
    """dict/list -> {caminho.pontuado: valor}; listas colapsam em `[]`."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_achatar(v, f"{prefixo}.{k}" if prefixo else str(k)))
    elif isinstance(obj, list):
        for item in obj:
            out.update(_achatar(item, prefixo + "[]"))
    elif prefixo:
        out[prefixo] = obj
    return out


def _exemplo(v):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return re.sub(r"\s+", " ", s)[:60]


def analisar_arquivo(nome):
    caminho = PASTA / nome
    if not caminho.exists():
        return None
    # split("\n"), não splitlines(): descrições trazem  /  literais
    # (ensure_ascii=False), e splitlines() quebraria a linha no meio do JSON.
    payloads = [json.loads(l)["payload"]
                for l in caminho.read_text(encoding="utf-8").split("\n") if l.strip()]
    n = len(payloads)
    preenchidos, exemplos = {}, {}
    for p in payloads:
        for campo, valor in _achatar(p).items():
            if campo.split(".")[-1].startswith("@"):
                continue  # metadado JSON-LD (@type, @context)
            if valor is None or valor == "":
                continue
            preenchidos[campo] = preenchidos.get(campo, 0) + 1
            exemplos.setdefault(campo, _exemplo(valor))

    mapeados = MAPEADOS[nome]
    nao_mapeados = []
    for campo in sorted(preenchidos, key=lambda c: -preenchidos[c]):
        if campo in mapeados:
            continue
        item = {"campo": campo, "preenchidos": preenchidos[campo],
                "pct": round(100 * preenchidos[campo] / n),
                "exemplo": exemplos[campo]}
        if nome == "sympla_catalogo.jsonl":
            item["solicitado_em_producao"] = campo.split(".")[0].split("[")[0] \
                in SOLICITADO_SYMPLA
        nao_mapeados.append(item)
    return {"n_eventos": n, "bytes": caminho.stat().st_size,
            "campos_no_payload": len(preenchidos),
            "campos_mapeados": len(mapeados & set(preenchidos)),
            "nao_mapeados": nao_mapeados}


def custo(resultados):
    total_raw = sum(r["bytes"] for r in resultados.values())
    saida = {"total_raw_kb": round(total_raw / 1024),
             "por_fonte": {nome: {"kb": round(r["bytes"] / 1024),
                                  "eventos": r["n_eventos"],
                                  "bytes_por_evento": round(r["bytes"] / r["n_eventos"])
                                  if r["n_eventos"] else None}
                           for nome, r in resultados.items()}}
    if DB.exists():
        db_bytes = DB.stat().st_size
        con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
        linhas = con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
        con.close()
        saida["base_atual"] = {
            "kb": round(db_bytes / 1024), "eventos": linhas,
            "bytes_por_evento": round(db_bytes / linhas) if linhas else None}
        saida["projecao_base_com_bronze_kb"] = round((db_bytes + total_raw) / 1024)
        saida["fator_crescimento"] = round((db_bytes + total_raw) / db_bytes, 1)
    return saida


def main():
    resultados = {}
    for nome in MAPEADOS:
        r = analisar_arquivo(nome)
        if r:
            resultados[nome] = r
    if not resultados:
        sys.exit("Nenhum JSONL encontrado — rode capturar.py antes.")

    c = custo(resultados)
    print("=" * 72)
    print("PASSO 2 — CUSTO do bruto")
    print("=" * 72)
    for nome, f in c["por_fonte"].items():
        print(f"  {nome:<28} {f['eventos']:>4} eventos  {f['kb']:>7,} KB  "
              f"(~{f['bytes_por_evento']:,} B/evento)")
    print(f"  {'TOTAL bruto':<28} {'':>4}          {c['total_raw_kb']:>7,} KB")
    if "base_atual" in c:
        b = c["base_atual"]
        print(f"\n  base atual (eventos.db): {b['kb']:,} KB, {b['eventos']} linhas "
              f"(~{b['bytes_por_evento']:,} B/evento)")
        print(f"  projeção com Bronze:     {c['projecao_base_com_bronze_kb']:,} KB "
              f"({c['fator_crescimento']}x a base atual)")
    else:
        print("\n  (data/eventos.db não existe — sem comparação)")

    print("\n" + "=" * 72)
    print("PASSO 3 — DESPERDÍCIO: campos preenchidos que o _normalizar descarta")
    print("=" * 72)
    for nome, r in resultados.items():
        nm = r["nao_mapeados"]
        print(f"\n--- {nome} ({r['n_eventos']} eventos; "
              f"{r['campos_no_payload']} campos no payload, "
              f"{r['campos_mapeados']} mapeados, {len(nm)} descartados) ---")
        for item in nm[:40]:
            marca = " $" if PRECO_RE.search(item["campo"]) else ""
            nota = ""
            if item.get("solicitado_em_producao") is False:
                nota = "  [nem solicitado: fora do `only`]"
            print(f"  {item['pct']:>3}%  {item['campo']:<44}{marca} "
                  f"ex: {item['exemplo']}{nota}")
        if len(nm) > 40:
            print(f"  ... +{len(nm) - 40} campos (lista completa em analise.json)")

    (PASTA / "analise.json").write_text(
        json.dumps({"custo": c, "desperdicio": resultados},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalhe completo salvo em {PASTA / 'analise.json'}")


if __name__ == "__main__":
    main()
