"""Probe determinístico: eventos de Brasília no Ticket and Go (ticketandgo.com.br).

Descoberta (2026-07-12, caçando no bundle Vite do site): o front (Vue) fala com

  https://production-api-v1-service.ticketandgo.com.br     (baseUrlApiTicketAndGo)

sem auth para leitura. Endpoints que importam:

  POST /eventos/pesquisa   body {"pesquisa": "<texto>"}
       -> {"data": {"eventos": [...]}}; "" (vazio) devolve o CATÁLOGO INTEIRO
       (~460 eventos, ~3,4 MB), cada evento já com descrição HTML completa.
  GET  /eventos/{slug}
       -> detalhe com "bilhetes" (lotes: nome + valor) e "sessoes";
       "taxa_conveniencia" (fração, ex.: 0.1 = 10%) é a taxa sobre o valor.

Os campos cidade/estado/cep vêm NULOS no catálogo — o local mora nos textos
"local" e "endereco_completo" ("SCTN - Plano Piloto, Brasília - DF, 70040-010").
O filtro DF então é textual: Brasília / " - DF" / CEP 70–73 nesses campos.

O GET /eventos/todos/lista visto no bundle responde 404 ("Evento não
encontrado" — a rota colide com /eventos/{slug}); a pesquisa vazia cobre.

Gera:
- resumo legível no stdout (eventos DF futuros + lotes de um deles)
- capturas/tng_catalogo_df.json (eventos DF do catálogo, payload bruto)
- capturas/tng_detalhe.json (UM detalhe bruto com bilhetes, referência de schema)

Uso: python spikes/zig-ticketandgo/probe_ticketandgo.py
"""

import json
import re
from datetime import date
from pathlib import Path

import requests

API = "https://production-api-v1-service.ticketandgo.com.br"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# CEPs do DF começam em 70–73 (Brasília e cidades-satélites).
_CEP_DF = re.compile(r"\b7[0-3]\d{3}-?\d{3}\b")
_UF_DF = re.compile(r"\bDF\b")

AQUI = Path(__file__).parent
CAPTURAS = AQUI / "capturas"


def do_df(ev):
    """Filtro textual de DF sobre local/endereco_completo (cidade/uf vêm nulos)."""
    texto = f"{ev.get('local') or ''} {ev.get('endereco_completo') or ''}"
    return ("brasília" in texto.casefold() or _UF_DF.search(texto)
            or _CEP_DF.search(texto))


if __name__ == "__main__":
    r = requests.post(f"{API}/eventos/pesquisa", json={"pesquisa": ""},
                      headers=UA, timeout=60)
    r.raise_for_status()
    catalogo = r.json()["data"]["eventos"]
    df = [e for e in catalogo if do_df(e)]
    hoje = date.today().isoformat()
    futuros = [e for e in df if (e.get("fim") or e.get("inicio") or "") >= hoje]

    print(f"== catálogo: {len(catalogo)} eventos | DF: {len(df)} "
          f"| DF futuros: {len(futuros)} ==")
    for e in futuros:
        print(f"- [{e['id']}] {e['nome']}\n"
              f"    {e.get('inicio')} {e.get('hora_incio')} | "
              f"{(e.get('endereco_completo') or e.get('local') or '')[:70]}\n"
              f"    https://www.ticketandgo.com.br/evento/{e['slug']} "
              f"| descrição: {len(e.get('descricao') or '')} chars")

    detalhe = None
    if futuros:
        alvo = futuros[0]
        r = requests.get(f"{API}/eventos/{alvo['slug']}", headers=UA, timeout=30)
        r.raise_for_status()
        detalhe = r.json()["data"]
        taxa = detalhe.get("taxa_conveniencia")
        print(f"\n== detalhe de \"{detalhe['nome']}\" "
              f"(taxa_conveniencia: {taxa}) ==")
        for b in detalhe.get("bilhetes") or []:
            valor = float(b.get("valor_bilhete") or b.get("valor") or 0)
            total = round(valor * (1 + float(taxa or 0)), 2)
            print(f"  lote: {b['nome']} | valor: {valor} | total c/ taxa: {total}")
        print(f"  sessoes: {json.dumps(detalhe.get('sessoes'), ensure_ascii=False)[:200]}")

    CAPTURAS.mkdir(exist_ok=True)
    (CAPTURAS / "tng_catalogo_df.json").write_text(
        json.dumps(df, ensure_ascii=False, indent=2), encoding="utf-8")
    if detalhe:
        (CAPTURAS / "tng_detalhe.json").write_text(
            json.dumps(detalhe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nCapturas em {CAPTURAS}/tng_*.json")
