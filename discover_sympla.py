"""Descobre a API interna que o front do Sympla usa para listar eventos.

Abre a pagina de listagem num Chromium headless, intercepta todas as
requisicoes XHR/fetch que retornam JSON e imprime os endpoints candidatos
junto com uma amostra da resposta. O objetivo e achar o endpoint de busca
para depois raspa-lo direto, sem navegador.
"""

import json
from playwright.sync_api import sync_playwright

LISTING_URL = "https://www.sympla.com.br/eventos/sao-paulo-sp"

# Guardamos as respostas JSON interessantes aqui
capturas = []


def eh_json(response):
    ct = response.headers.get("content-type", "")
    return "application/json" in ct


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
        )
        page = context.new_page()

        def on_response(response):
            try:
                url = response.url
                if not eh_json(response):
                    return
                # ignora assets/telemetria obvios
                if any(x in url for x in ("_next/", "google", "facebook", "hotjar",
                                          "segment", "sentry", "clarity")):
                    return
                body = response.json()
                capturas.append({
                    "url": url,
                    "status": response.status,
                    "method": response.request.method,
                    "amostra": body,
                })
            except Exception:
                pass

        page.on("response", on_response)

        print(f"Abrindo {LISTING_URL} ...")
        page.goto(LISTING_URL, wait_until="networkidle", timeout=60000)
        # rola a pagina pra disparar carregamento lazy de mais eventos
        for _ in range(3):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)

        browser.close()

    print(f"\n=== {len(capturas)} respostas JSON capturadas ===\n")
    for i, c in enumerate(capturas):
        # resume a amostra pra nao poluir
        amostra = c["amostra"]
        if isinstance(amostra, dict):
            chaves = list(amostra.keys())
            resumo = f"dict com chaves: {chaves}"
        elif isinstance(amostra, list):
            resumo = f"lista com {len(amostra)} itens; item[0] keys: " + (
                str(list(amostra[0].keys())) if amostra and isinstance(amostra[0], dict) else "?")
        else:
            resumo = type(amostra).__name__
        print(f"[{i}] {c['method']} {c['status']} {c['url']}")
        print(f"     {resumo}\n")

    # salva tudo pra inspecao detalhada
    saida = "capturas_sympla.json"
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(capturas, f, ensure_ascii=False, indent=2)
    print(f"Detalhes completos salvos em {saida}")


if __name__ == "__main__":
    main()
