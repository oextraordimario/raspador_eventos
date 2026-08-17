"""Definições do Dagster — o ÚNICO arquivo do projeto que importa `dagster`.

Ele é mais um chamador dos passos, na mesma posição que o `atualizar.py` (CLI)
ocupa: quem sabe raspar, tratar e relatar é `pipeline/passos.py` e
`tratamento/ciclo.py`; aqui só se declara o grafo, o job e o schedule. Se o
Dagster não vingar, apaga-se este arquivo e nada mais precisa mudar
(spec 20260814_orquestracao-dagster §5.1, decisão D5).

Carregado pelo servidor gRPC da code location, por caminho absoluto:

    dagster api grpc -h 0.0.0.0 -p 4000 -f /opt/raspador/src/pipeline/definitions.py

**Fatia 2 — só o asset de diagnóstico.** O grafo de verdade (uma coleta por
fonte, o tratamento numa transação só, o laço do TMDB) entra na fatia 3, contra
`eventos_teste`. O que esta fatia prova é o AMBIENTE: que a imagem tem tudo que
o raspador importa, que a code location carrega o código do repo do raspador, e
que este container alcança o Neon num tempo razoável.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Importável por um carregador que não põe `src/` no sys.path — é o caso do
# `-f` do Dagster, que carrega por caminho absoluto. Idempotente, e o mesmo
# que o `passos.py` faz. O `PYTHONPATH` do compose cobre o mesmo buraco; os
# dois juntos porque a code location que falha por import mostra na UI só
# "location failed to load", nunca o ImportError de verdade.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dagster as dg                                              # noqa: E402

from base import conexao                                          # noqa: E402
from pipeline import passos                                       # noqa: E402

# `passos` ainda não é CHAMADO nesta fatia, e o import não é decorativo: é ele
# que aplica o `FORCAR_IPV4` (o patch mora no import de `passos.py`, por ser
# decisão de pipeline). Sem esta linha, medir a conexão com e sem a variável
# daria o mesmo número e a medição da fatia 2 não valeria nada. De quebra, o
# import puxa a cadeia inteira — coleta, tratamento, serviço — e é assim que
# dependência faltando na imagem aparece como code location vermelha em vez de
# como um erro no meio da primeira rodada de produção.
_ = passos


@dg.asset(key=["tratado", "contagem_eventos"], group_name="diagnostico",
          description="Sonda da fatia 2: conta `tratado.eventos` e mede o "
                      "tempo de abertura da conexão com o Neon. Só LÊ.")
def contagem_eventos(context: dg.AssetExecutionContext):
    agora = datetime.now(timezone.utc).isoformat()

    # Conexão curta, como todo passo do pipeline: conexão parada durante
    # minutos de rede é derrubada em silêncio pelo Neon (visto no Zig).
    marca = time.perf_counter()
    con = conexao.conectar()
    conexao_s = time.perf_counter() - marca
    try:
        # `conectar()` devolve conexão com `row_factory=dict_row` — a linha é
        # dicionário, não tupla, então toda contagem precisa de apelido.
        with con.cursor() as cur:
            total = cur.execute("SELECT count(*) AS n FROM tratado.eventos"
                                ).fetchone()["n"]
            futuros = cur.execute(
                "SELECT count(*) AS n FROM tratado.eventos "
                "WHERE start_date >= %s", (agora,)).fetchone()["n"]
            # `dbname` sai da conexão, não do env: é o que responde "esta
            # rodada foi contra produção ou contra eventos_teste?" sem levar
            # pedaço de connection string para o event log — a metadata fica
            # gravada em Postgres e visível na UI, que não tem autenticação.
            base = con.info.dbname
    finally:
        con.close()

    # O pipeline inteiro fala por `print`; dentro de um asset, `context.log`
    # é o que a UI mostra na aba de logs estruturados (§6.6).
    context.log.info(f"{base}: {total} eventos, {futuros} futuros. "
                     f"Conexão aberta em {conexao_s:.2f}s.")
    return dg.MaterializeResult(metadata={
        "base": base,
        "eventos": total,
        "futuros": futuros,
        "conexao_s": round(conexao_s, 2),
    })


defs = dg.Definitions(assets=[contagem_eventos])
