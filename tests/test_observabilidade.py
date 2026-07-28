"""Teste executável do NI-19 (alinhamento à Constituição): tabela execucoes +
comparação de coleta, marcação de eventos sumidos do catálogo (e efeito na
consulta) e janela temporal do precificar. Usa o banco descartável
eventos_teste no Neon (não toca a base de produção — ver tests/base_teste.py).
Spec: docs/specs/20260710_alinhamento-constituicao.

Uso: python tests/test_observabilidade.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from base import conexao
from pipeline import execucoes
from tratamento import busca
from tratamento import comum
from pipeline import atualizar  # noqa: E402
from servico import consulta  # noqa: E402
from coleta import ingresse, sympla  # noqa: E402

import base_teste  # noqa: E402

# Redireciona a base para o banco descartável antes de qualquer conectar().
base_teste.preparar()

AGORA = datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def evento(id_, **kw):
    fonte = id_.split(":")[0]
    e = {
        "id": id_, "fonte": fonte, "id_nativo": id_.split(":")[1],
        "nome": f"Evento {id_}", "start_date": iso(AGORA + timedelta(days=5)),
        "end_date": None, "cidade": "Brasília", "estado": "DF",
        "local_nome": None, "endereco": None, "lat": None, "lon": None,
        "categoria": None, "organizador": None, "url": f"https://x/{id_}",
        "imagem": None, "raspado_em": iso(AGORA - timedelta(days=3)),
    }
    e.update(kw)
    return e


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
    comum.upsert_eventos(con, [
        # raspado_em default (3 dias atrás) = NÃO reapareceu nesta rodada
        evento("sympla:velho"),
        evento("sympla:passado", start_date=iso(AGORA - timedelta(days=2))),
        evento("shotgun:fora"),  # fonte não raspada nesta rodada: intocado
        # reapareceu agora (raspado_em novo)
        evento("sympla:revisto", raspado_em=iso(AGORA + timedelta(seconds=5))),
    ])
    sumidos = atualizar._marcar_sumidos(
        con, {"sympla": {"coletados": 1}, "shotgun": {"erro": "x"}}, iso(AGORA))
    marcas = {r["id"]: r["sumido"]
              for r in con.execute("SELECT id, sumido FROM tratado.eventos")}
    assert marcas["sympla:velho"] == 1, "futuro não revisto tinha que sumir"
    assert marcas["sympla:passado"] == 0, "evento passado nunca é marcado"
    assert marcas["sympla:revisto"] == 0, "quem reapareceu não pode sumir"
    assert marcas["shotgun:fora"] == 0, "fonte com erro não condena seus eventos"
    assert sumidos == [("Evento sympla:velho", "sympla")], sumidos
    print("sumido: marca futuro não revisto; poupa passado, revisto e fonte com erro — ok")

    # ── sumido some da consulta por padrão; incluir_ruido mostra ──
    busca.reconstruir_fts(con)
    urls = {e["url"] for e in consulta.buscar_eventos(limite=50)}
    assert "https://x/sympla:velho" not in urls, "sumido vazou na consulta"
    assert "https://x/sympla:revisto" in urls
    urls_debug = {e["url"] for e in consulta.buscar_eventos(limite=50,
                                                            incluir_ruido=True)}
    assert "https://x/sympla:velho" in urls_debug
    print("consulta: esconde sumido por padrão, incluir_ruido mostra — ok")

    # ── idempotência: reaparecer no upsert desmarca na rodada seguinte ──
    comum.upsert_eventos(con, [
        evento("sympla:velho", raspado_em=iso(AGORA + timedelta(minutes=1)))])
    atualizar._marcar_sumidos(con, {"sympla": {"coletados": 1}}, iso(AGORA))
    assert con.execute("SELECT sumido FROM tratado.eventos WHERE id = 'sympla:velho'"
                       ).fetchone()["sumido"] == 0
    print("sumido: evento que reaparece é desmarcado — ok")

    # ── NI-59: coleta ZERADA não condena a fonte (o caso Shotgun no CI) ──
    # shotgun:fora é futuro e não foi revisto — sem a guarda, uma rodada que
    # devolve 0 COM sucesso marcaria ele (e toda a agenda da fonte).
    atualizar._marcar_sumidos(
        con, {"shotgun": {"coletados": 0, "total_site": 0}}, iso(AGORA))
    assert con.execute("SELECT sumido FROM tratado.eventos WHERE id = 'shotgun:fora'"
                       ).fetchone()["sumido"] == 0, \
        "coleta zerada não pode marcar sumido (NI-59)"
    # e a fonte que coletou de verdade continua marcando
    sumidos = atualizar._marcar_sumidos(
        con, {"shotgun": {"coletados": 3, "total_site": 3}}, iso(AGORA))
    assert con.execute("SELECT sumido FROM tratado.eventos WHERE id = 'shotgun:fora'"
                       ).fetchone()["sumido"] == 1, \
        "fonte que coletou tem que continuar marcando o que não reapareceu"
    assert sumidos == [("Evento shotgun:fora", "shotgun")], sumidos
    print("sumido: coleta zerada é pulada; coleta real continua marcando — ok")

    # ── janela do precificar: 7 dias entra, 60 fica fora, --tudo cobre ──
    comum.upsert_eventos(con, [
        evento("ingresse:perto", start_date=iso(AGORA + timedelta(days=7)),
               raspado_em=iso(AGORA)),
        evento("ingresse:longe", start_date=iso(AGORA + timedelta(days=60)),
               raspado_em=iso(AGORA)),
        evento("sympla:perto", start_date=iso(AGORA + timedelta(days=7)),
               raspado_em=iso(AGORA), url="https://www.sympla.com.br/e/111",
               descricao="tem descrição validada"),
        # sem descrição = sem âncora NI-17: nunca é alvo, nem com --tudo
        evento("sympla:sem-descricao", start_date=iso(AGORA + timedelta(days=7)),
               raspado_em=iso(AGORA), url="https://www.sympla.com.br/e/222"),
    ])
    chamados = []
    sympla.raspar_tickets = lambda id_url: (chamados.append(f"sympla:{id_url}"),
                                            {"payload": {"tickets": []}})[1]
    ingresse.raspar_tickets = lambda id_nativo: (
        chamados.append(f"ingresse:{id_nativo}"), {"payload": {"detail": {}}})[1]

    erros = []
    r = atualizar._precificar(con, erros, pausa=0)
    assert "ingresse:perto" in chamados and "sympla:111" in chamados, chamados
    assert "ingresse:longe" not in chamados, "60 dias tinha que ficar fora da janela"
    assert not any("222" in c for c in chamados), "sympla sem descrição não é alvo"
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

    con.close()
    print("\nTudo certo.")


if __name__ == "__main__":
    main()
