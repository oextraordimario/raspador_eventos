"""Mede o que o `FORCAR_IPV4` faz NESTA máquina — e se ele ainda faz algo.

Fora do pipeline: é ferramenta de diagnóstico, roda quando o raspador muda de
hospedeiro (foi escrita para a fatia 2 da spec 20260814_orquestracao-dagster,
quando a rodada saiu do notebook para o servidor do homelab).

    python src/ferramentas/diag_rede.py

A variável existe porque, numa rede com IPv6 quebrado, `urllib` e `psycopg`
tentam os endereços v6 em SEQUÊNCIA e pagam ~20 s de timeout por endereço antes
de cair no IPv4 (nada de happy eyeballs). O remédio é um filtro no
`socket.getaddrinfo`, e ele mora no import de `pipeline/passos.py`.

Por isso a medição roda em DOIS SUBPROCESSOS do próprio arquivo, um com
`FORCAR_IPV4=1` e outro sem: o que se mede é o patch de verdade, importado do
lugar de verdade, e não uma imitação dele escrita aqui.

Mede três coisas, porque elas falham separado: a RESOLUÇÃO do nome (quantos
endereços de cada família vêm), a conexão com o **Neon** e uma requisição
**HTTP** a uma fonte. Só a terceira representa o grosso de uma rodada — são
centenas de requisições — e foi justamente ela que a fatia 2 precisou medir,
porque a conexão com a base deu empate.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from base import conexao  # noqa: E402

# Página leve de uma fonte real: o que importa é o caminho de rede até ela,
# não o conteúdo.
ALVO_HTTP = "https://www.sympla.com.br/robots.txt"


def _familias(host):
    """Quantos endereços de cada família o resolvedor devolve para o host."""
    try:
        infos = socket.getaddrinfo(host, 443)
    except OSError as e:
        return {"erro": str(e)}
    return {"v4": sum(1 for i in infos if i[0] == socket.AF_INET),
            "v6": sum(1 for i in infos if i[0] == socket.AF_INET6)}


def _cronometrar(funcao):
    marca = time.perf_counter()
    try:
        funcao()
        erro = ""
    except Exception as e:                                   # noqa: BLE001
        erro = f"{type(e).__name__}: {e}"
    return round(time.perf_counter() - marca, 2), erro


def _medir():
    """Roda no subprocesso filho, já com (ou sem) o patch aplicado."""
    url = conexao.env_var("EVENTOS_DB_URL") or ""
    host_base = urlparse(url).hostname or ""

    def _abrir_base():
        conexao.conectar().close()

    def _get():
        # UA de navegador porque a borda do Sympla responde 403 a `urllib` cru —
        # e um 403 mediria o caminho de rede igual, mas confunde quem lê a saída.
        pedido = urllib.request.Request(ALVO_HTTP, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        urllib.request.urlopen(pedido, timeout=90).read(64)

    base_s, base_erro = _cronometrar(_abrir_base)
    http_s, http_erro = _cronometrar(_get)
    return {
        "patch_ativo": bool(conexao.env_var("FORCAR_IPV4")),
        "dns_base": _familias(host_base),
        "dns_fonte": _familias(urlparse(ALVO_HTTP).hostname),
        "base_s": base_s, "base_erro": base_erro,
        "http_s": http_s, "http_erro": http_erro,
    }


def _rodar(forcar):
    """Sobe um filho com FORCAR_IPV4 ligado ou desligado e colhe o resultado."""
    env = dict(os.environ, FORCAR_IPV4="1" if forcar else "")
    saida = subprocess.run([sys.executable, __file__, "--filho"],
                           capture_output=True, text=True, env=env)
    for linha in saida.stdout.splitlines():
        if linha.startswith("{"):
            return json.loads(linha)
    return {"erro": (saida.stderr or saida.stdout).strip()[-400:]}


def main():
    print(f"Alvo HTTP: {ALVO_HTTP}")
    # Passada de aquecimento, DESCARTADA: cache de DNS e sessão TLS fazem a
    # primeira medição custar mais que as seguintes, e como a ordem aqui é fixa
    # quem pagaria a conta seria sempre o lado "sem patch". No servidor do
    # homelab, em 17/08, isso apareceu como 0,73 s contra 0,25 s no Neon — que
    # na segunda rodada viraram 0,26 e 0,19. Sem isto, a ferramenta recomenda
    # ligar a variável em rede que não precisa dela.
    _rodar(False)
    for forcar in (False, True):
        r = _rodar(forcar)
        rotulo = "COM FORCAR_IPV4" if forcar else "sem FORCAR_IPV4"
        if "erro" in r:
            print(f"{rotulo}: FALHOU — {r['erro']}")
            continue
        # `patch_ativo` sai do filho, não da intenção do pai: é a prova de que
        # o import de `passos` viu a variável.
        print(f"{rotulo} (patch visto pelo filho: {r['patch_ativo']})")
        print(f"  DNS  base={r['dns_base']}  fonte={r['dns_fonte']}")
        print(f"  Neon {r['base_s']}s {r['base_erro']}")
        print(f"  HTTP {r['http_s']}s {r['http_erro']}")
    print("\nDiferença pequena nos dois = a rede desta máquina não precisa da "
          "variável.\nDiferença de dezenas de segundos no HTTP = precisa, e a "
          "rodada inteira depende dela.")


if __name__ == "__main__":
    if "--filho" in sys.argv:
        # O import é o que aplica (ou não) o patch — e ele imprime uma linha
        # própria quando aplica, por isso o pai lê só a linha que começa com {.
        from pipeline import passos                          # noqa: F401
        print(json.dumps(_medir()))
    else:
        main()
