"""Teste executável do NI-19 (alinhamento à Constituição): tabela execucoes +
comparação de coleta, derivação de `sumido` a partir de `operacao.coletas` (e
efeito na consulta) e janela temporal do precificar. Usa o banco descartável
eventos_teste no Neon (não toca a base de produção — ver tests/base_teste.py).
Specs: 20260710_alinhamento-constituicao, 20260728_arquitetura-medalhao §8.1.

Uso: python tests/test_observabilidade.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from base import conexao
from coleta import gravar
from pipeline import execucoes
from tratamento import busca, comum, sumido
from pipeline import atualizar  # noqa: E402
from servico import consulta  # noqa: E402
from coleta import ingresse, sympla  # noqa: E402

import base_teste  # noqa: E402

# Redireciona a base para o banco descartável antes de qualquer conectar().
base_teste.preparar()

AGORA = datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def catalogo(con, id_, visto=None, **kw):
    """Grava um payload de catálogo no cru e devolve o id do evento.

    O teste escreve no CRU, não na prata: desde a fatia 7 é o tratamento que
    produz `tratado.eventos`, e escrever direto lá testaria um caminho que o
    pipeline não usa mais.
    """
    fonte, _, id_nativo = id_.partition(":")
    ts = iso(visto or (AGORA - timedelta(days=3)))
    if fonte == "sympla":
        p = {"id": id_nativo, "name": f"Evento {id_}", "location": {},
             "start_date": iso(AGORA + timedelta(days=5)),
             "url": f"https://x/{id_}"}
    elif fonte == "ingresse":
        p = {"id": id_nativo, "title": f"Evento {id_}", "place": {},
             "event_date": iso(AGORA + timedelta(days=5)),
             "slug": id_.replace(":", "-")}
    else:  # shotgun: a chave é o slug e cidade/estado são colunas do cru
        p = {"name": f"Evento {id_}", "location": {},
             "startDate": iso(AGORA + timedelta(days=5)),
             "url": f"https://x/{id_}"}
    p.update(kw)
    extras = ({"cidade_label": "Brasília", "estado_label": "DF"}
              if fonte == "shotgun" else {})
    gravar.gravar(con, fonte, id_nativo, "catalogo", p, ts, **extras)
    return id_


def coleta(con, fonte, quando, **kw):
    """Registra uma coleta em operacao.coletas (a âncora do `sumido`)."""
    execucoes.registrar_coleta(con, fonte, iso(quando), iso(quando),
                               {"coletados": 1, "total_site": 1, **kw})


def marcas(con):
    return {r["id"]: r["sumido"]
            for r in con.execute("SELECT id, sumido FROM tratado.eventos")}


def main():
    con = conexao.conectar()

    # ── execucoes: registro + última + coleta anterior por fonte ──
    execucoes.registrar_execucao(
        con, iso(AGORA - timedelta(days=2)), 100.0, "completo",
        {"sympla": {"coletados": 200, "total_site": 210},
         "ingresse": {"coletados": 30, "total_site": 30}},
        {"ruido": 5}, [])
    execucoes.registrar_execucao(
        con, iso(AGORA - timedelta(days=1)), 90.0, "sem-shotgun",
        {"sympla": {"erro": "HTTPError: 500"}},  # falhou: não vale como coleta
        {"ruido": 5}, [{"passo": "descrever", "evento_id": "sympla:9",
                        "erro": "timeout"}])
    ult = execucoes.ultima_execucao(con)
    assert ult["modo"] == "sem-shotgun" and ult["fontes"]["sympla"]["erro"]
    assert ult["erros"][0]["evento_id"] == "sympla:9", "erros não round-tripam"
    ant = atualizar._coleta_anterior(con)
    assert ant["sympla"][0] == 200, "rodada com erro não pode valer como coleta"
    assert ant["ingresse"][0] == 30
    print("execucoes: registro round-tripa; coleta anterior ignora rodada com erro — ok")

    # ── alerta de queda: 200 -> 80 é queda de 60% (> QUEDA_ALERTA de 50%) ──
    assert 80 < 200 * (1 - atualizar.QUEDA_ALERTA), "cenário do teste ficou inválido"
    assert 120 > 200 * (1 - atualizar.QUEDA_ALERTA), "120 não deveria alertar"
    print(f"execucoes: limiar de alerta em {atualizar.QUEDA_ALERTA:.0%} — ok")

    # ── sumido: futuro não revisto marca; passado e revisto não marcam ──
    # visto_em default (3 dias atrás) = NÃO reapareceu nesta rodada
    catalogo(con, "sympla:velho")
    catalogo(con, "sympla:passado", start_date=iso(AGORA - timedelta(days=2)))
    catalogo(con, "shotgun:fora")   # fonte que FALHOU nesta rodada: intocado
    catalogo(con, "sympla:revisto", visto=AGORA + timedelta(seconds=5))
    comum.aplicar(con)
    coleta(con, "sympla", AGORA)
    coleta(con, "shotgun", AGORA, erro="HTTPError: 500")
    sumidos = sumido.aplicar(con)
    m = marcas(con)
    assert m["sympla:velho"] == 1, "futuro não revisto tinha que sumir"
    assert m["sympla:passado"] == 0, "evento passado nunca é marcado"
    assert m["sympla:revisto"] == 0, "quem reapareceu não pode sumir"
    assert m["shotgun:fora"] == 0, "fonte com erro não condena seus eventos"
    assert sumidos == [("Evento sympla:velho", "sympla")], sumidos
    print("sumido: marca futuro não revisto; poupa passado, revisto e fonte com erro — ok")

    # ── sumido some da consulta por padrão; incluir_ruido mostra ──
    busca.reconstruir_fts(con)
    con.commit()
    urls = {e["url"] for e in consulta.buscar_eventos(limite=50)}
    assert "https://x/sympla:velho" not in urls, "sumido vazou na consulta"
    assert "https://x/sympla:revisto" in urls
    urls_debug = {e["url"] for e in consulta.buscar_eventos(limite=50,
                                                            incluir_ruido=True)}
    assert "https://x/sympla:velho" in urls_debug
    print("consulta: esconde sumido por padrão, incluir_ruido mostra — ok")

    # ── idempotência: reaparecer no cru desmarca na rodada seguinte ──
    catalogo(con, "sympla:velho", visto=AGORA + timedelta(minutes=1))
    comum.aplicar(con)
    sumido.aplicar(con)
    assert marcas(con)["sympla:velho"] == 0, "quem reaparece tem que desmarcar"
    print("sumido: evento que reaparece é desmarcado — ok")

    # ── NI-59: coleta ZERADA não condena a fonte (o caso Shotgun no CI) ──
    # shotgun:fora é futuro e não foi revisto — sem a guarda, uma rodada que
    # devolve 0 COM sucesso marcaria ele (e toda a agenda da fonte).
    coleta(con, "shotgun", AGORA + timedelta(minutes=2), coletados=0,
           total_site=0)
    sumido.aplicar(con)
    assert marcas(con)["shotgun:fora"] == 0, \
        "coleta zerada não pode marcar sumido (NI-59)"
    # e a fonte que coletou de verdade continua marcando
    coleta(con, "shotgun", AGORA + timedelta(minutes=3), coletados=3,
           total_site=3)
    sumidos = sumido.aplicar(con)
    assert marcas(con)["shotgun:fora"] == 1, \
        "fonte que coletou tem que continuar marcando o que não reapareceu"
    assert ("Evento shotgun:fora", "shotgun") in sumidos, sumidos
    print("sumido: coleta zerada é pulada; coleta real continua marcando — ok")

    # ── janela do precificar: 7 dias entra, 60 fica fora, --tudo cobre ──
    # Tudo com visto_em DEPOIS da última coleta boa de cada fonte, senão o
    # próprio filtro de sumido tiraria da fila (é o mesmo critério).
    agora_prec = AGORA + timedelta(minutes=10)
    catalogo(con, "ingresse:perto", visto=agora_prec,
             event_date=iso(AGORA + timedelta(days=7)))
    catalogo(con, "ingresse:longe", visto=agora_prec,
             event_date=iso(AGORA + timedelta(days=60)))
    catalogo(con, "sympla:perto", visto=agora_prec,
             start_date=iso(AGORA + timedelta(days=7)),
             url="https://www.sympla.com.br/e/111")
    # sem payload de detalhe = sem âncora NI-17: nunca é alvo, nem com --tudo
    catalogo(con, "sympla:sem-detalhe", visto=agora_prec,
             start_date=iso(AGORA + timedelta(days=7)),
             url="https://www.sympla.com.br/e/222")
    gravar.gravar(con, "sympla", "perto", "detalhe",
                  {"name": "Evento sympla:perto", "detail": "<p>tem</p>"},
                  iso(agora_prec))
    coleta(con, "sympla", agora_prec)
    coleta(con, "ingresse", agora_prec)
    comum.aplicar(con)

    chamados = []
    sympla.raspar_tickets = lambda id_url: (chamados.append(f"sympla:{id_url}"),
                                            {"payload": {"tickets": []}})[1]
    ingresse.raspar_tickets = lambda id_nativo: (
        chamados.append(f"ingresse:{id_nativo}"), {"payload": {"detail": {}}})[1]

    erros = []
    r = atualizar._precificar(con, erros, pausa=0)
    assert "ingresse:perto" in chamados and "sympla:111" in chamados, chamados
    assert "ingresse:longe" not in chamados, "60 dias tinha que ficar fora da janela"
    assert not any("222" in c for c in chamados), "sympla sem detalhe não é alvo"
    assert r["fora_janela"] == 1 and r["falhas"] == 0 and not erros, r
    print(f"precificar: janela de {atualizar.JANELA_PRECIFICAR_DIAS} dias "
          "poupa evento distante e reporta fora_janela — ok")

    chamados.clear()
    r = atualizar._precificar(con, erros, pausa=0, tudo=True)
    assert "ingresse:longe" in chamados, "--precificar-tudo tinha que incluir o distante"
    assert r["fora_janela"] == 0, r
    print("precificar: --precificar-tudo cobre todos os futuros — ok")

    # ── falha por evento vira registro em erros, não só contador ──
    def quebra(id_nativo):
        raise ValueError("boom")
    ingresse.raspar_tickets = quebra
    erros = []
    r = atualizar._precificar(con, erros, pausa=0)  # só ingresse:perto falha
    assert r["falhas"] == 1 and len(erros) == 1, (r, erros)
    assert erros[0] == {"passo": "precificar", "evento_id": "ingresse:perto",
                        "erro": "ValueError: boom"}, erros
    print("precificar: falha registra QUAL evento e por quê — ok")

    con.commit()
    con.close()
    print("\nTudo certo.")


if __name__ == "__main__":
    main()
