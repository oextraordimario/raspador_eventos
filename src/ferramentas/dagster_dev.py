"""Sobe o Dagster NO LAPTOP, apontado para a base de teste.

    python src/ferramentas/dagster_dev.py          # UI em http://127.0.0.1:3070

Existe para encurtar o laço de quem mexe no grafo. Ver o efeito de uma mudança
no `definitions.py` no servidor custa commit -> push -> `git pull` -> `docker
compose restart raspador_code`; aqui custa um F5. O que mais se ganha é o que
só se vê olhando: agrupamento, nome de chave, o que o desenho explica para quem
chega — que é o motivo nº 1 da migração.

**ESTE ARQUIVO É DUAS COISAS.** Rodado (`python ...`), é o lançador: chama o
`dagster dev` do venv apontando o `-f` para si mesmo. Carregado pelo Dagster
(o code server e, no spawn do executor, cada step), é o módulo que **redireciona
a conexão para a base de teste antes de o grafo existir** e reexporta o `defs`
do `pipeline/definitions.py`. Um arquivo só porque as duas metades precisam
concordar sobre qual base é essa, e duas fontes divergiriam em silêncio.

**A ARMADILHA QUE ISTO EVITA, medida em 18/08/2026.** O CLI do Dagster lê o
`.env` do diretório de trabalho e o injeta com `os.environ[chave] = valor` —
ou seja, **sobrescrevendo** o ambiente que o processo já tinha. A raiz deste
repo tem um `.env` cujo `EVENTOS_DB_URL` é **produção**. A primeira versão
deste arquivo passava a URL de teste no ambiente do subprocesso, o que parecia
bastar; uma sonda que só imprimia o nome do banco visto pelo step provou o
contrário — passando `.../BANCO_DE_TESTE_FALSO`, o step leu `eventos`. Um
clique em `tratamento` teria reconstruído a prata de produção a partir do cru
de produção, e a tela não teria dito nada.

Por isso o redirecionamento é o mesmo dos testes (`tests/base_teste.py`):
`conexao.DB_URL`, que tem precedência sobre a variável de ambiente e sobre o
`.env`, mais a guarda de nome — URL sem "teste" não sobe. A conferência em run
continua sendo o asset `operacao/schema`, que publica `base=` na metadata.

*(Corolário para o servidor: se um dia aparecer um `.env` dentro de
`/srv/raspador_eventos`, ele passa a vencer o `env_file` do compose. Hoje não
existe — o clone é limpo e o `.env` é gitignorado.)*

**O que é diferente daqui para o servidor** (assumido, não acidente):

- storage local é SQLite em `.dagster/` (gitignorado, descartável); lá é
  Postgres, e é lá que mora o histórico que vale.
- não há `dagster.yaml`: valem os defaults. Config de instância (pools,
  concorrência, retenção) só existe no servidor, e é assim que se quer — o
  laptop não é o lugar de descobrir que um valor de instância mudou.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from base import conexao                                          # noqa: E402

# A 3000 é o padrão do Dagster e também onde o `next dev` cai quando não passa
# pelo script do package.json: as duas coisas do projeto que sobem servidor
# local brigariam pela mesma porta.
PORTA = "3070"

VENV = RAIZ / ".venv-dagster"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def apontar_para_teste():
    """Redireciona TODA conexão deste processo para `eventos_teste`."""
    url = conexao.env_var("EVENTOS_DB_URL_TESTE")
    if not url or "teste" not in url:
        raise SystemExit(
            "EVENTOS_DB_URL_TESTE ausente, ou não parece ser a base de teste.\n"
            "Sem ela não se sobe nada: o fallback do `.env` é a PRODUÇÃO, e o "
            "grafo local materializa de verdade.")
    conexao.DB_URL = url
    return url


URL_TESTE = apontar_para_teste()

# Só quando carregado DENTRO do venv (como code location). No lançador, que
# roda no python do sistema, `dagster` não existe e não precisa existir.
if importlib.util.find_spec("dagster"):
    from pipeline.definitions import defs                         # noqa: E402,F401


def main(argv):
    if not PY.exists():
        raise SystemExit(
            f"venv do Dagster não encontrado em {VENV}.\n"
            f"  py -3.12 -m venv .venv-dagster\n"
            f"  .venv-dagster/Scripts/python.exe -m pip install "
            f"-r requirements-dagster.txt")

    env = dict(os.environ, DAGSTER_HOME=str(RAIZ / ".dagster"))
    Path(env["DAGSTER_HOME"]).mkdir(exist_ok=True)

    # `--spike` carrega TAMBÉM o experimento de `spikes/` como segunda code
    # location. São dois grafos lado a lado na mesma UI, que é o ponto: o
    # desenho real e o alternativo se comparam olhando, não lendo diff.
    #
    # Por um workspace, e não por dois `-f`: com `-f` repetido a UI nomeia cada
    # location pelo NOME DO ARQUIVO, e os dois grafos apareceriam como
    # "dagster_dev.py" e "definitions.py" — sendo que o `definitions.py` é o
    # spike, e o do pipeline real é o outro. Justamente na tela feita para
    # comparar os dois, o rótulo mentiria.
    fontes = [("raspador", "src/ferramentas/dagster_dev.py")]
    if "--spike" in argv:
        argv = [a for a in argv if a != "--spike"]
        fontes.append(("spike_sympla", "spikes/dagster_sympla/definitions.py"))
    # Caminho ABSOLUTO e `working_directory` explícito: o `relative_path` do
    # workspace resolve contra a pasta do YAML — que aqui é `.dagster/` —, e
    # não contra o diretório de trabalho. Com caminho relativo, as duas
    # locations falham ao carregar procurando `.dagster/src/...`.
    workspace = Path(env["DAGSTER_HOME"]) / "workspace.yaml"
    workspace.write_text("load_from:\n" + "".join(
        f"  - python_file:\n      relative_path: {(RAIZ / caminho).as_posix()}\n"
        f"      working_directory: {RAIZ.as_posix()}\n"
        f"      location_name: {nome}\n" for nome, caminho in fontes),
        encoding="utf-8")

    # Só o nome da base: a URL inteira carrega usuário e senha do Neon, e esta
    # linha existe para ser lida antes de clicar em qualquer coisa.
    print(f"base  : {URL_TESTE.rsplit('/', 1)[-1].split('?')[0]}")
    print(f"home  : {env['DAGSTER_HOME']}")
    print(f"UI    : http://127.0.0.1:{PORTA}\n")

    return subprocess.call(
        [str(PY), "-m", "dagster", "dev", "-w", str(workspace), "-p", PORTA,
         *argv], env=env, cwd=RAIZ)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
