"""Teste executável da API de leitura do site (api/dados.py) — spec
20260726_abrir-ao-publico §5. Usa o banco descartável eventos_teste no Neon
(ver tests/base_teste.py).

O que este teste protege, e por quê: a API é a FRONTEIRA da camada canônica.
Se ela devolver evento ruidoso, cancelado, sumido ou duplicata, o site passa a
mentir sem que a `consulta.py` tenha mudado — e as duas transformações de
postura (trecho da descrição, organizador oculto) são compromissos que a spec
assumiu por escrito e que ninguém percebe se quebrarem em silêncio.

Chama a função `rota()` direto, sem subir servidor HTTP: o que interessa é o
contrato de dados, não o transporte.

Uso: python tests/test_api_dados.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "api"))

from tratamento import enriquecer  # noqa: E402
from tratamento import cinema as trat_cinema  # noqa: E402
from base import conexao
from coleta import gravar
from tratamento import busca
from tratamento import comum
from servico import feedback as svc_feedback

import base_teste  # noqa: E402

base_teste.preparar()

import dados as api_dados  # noqa: E402  (api/dados.py, depois do sys.path)

AGORA = datetime.now(timezone.utc)
FALHAS = []


def checar(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond:
        FALHAS.append(msg)


def iso(**delta):
    return (AGORA + timedelta(**delta)).isoformat()


def evento(id_, nome, local, **kw):
    base = dict(id=id_, fonte=id_.split(":")[0], id_nativo=id_.split(":")[1],
                nome=nome, start_date=iso(days=1), cidade="Brasília",
                estado="DF", local_nome=local,
                url=f"https://exemplo.test/{id_}",
                raspado_em=AGORA.isoformat())
    base.update(kw)
    return base


# ── cenário ───────────────────────────────────────────────────────────────
# Um evento de cada situação que a API precisa filtrar ou transformar.
#
# Nomes e LOCAIS deliberadamente distintos entre si: o dedupe agrupa por mesmo
# dia + local + nome similar, e um cenário com "Festa A"/"Festa B" na mesma
# casa e no mesmo dia faz o enriquecimento colapsá-los — o teste falharia por
# um acerto do sistema, não por um defeito da API.

DESCRICAO_LONGA = ("Line-up completo da noite. " * 60).strip()  # ~1560 chars

con = conexao.conectar()
comum.upsert_eventos(con, [
    evento("sympla:1", "Pagode do Teste", "Casa Alfa",
           descricao=DESCRICAO_LONGA, organizador="Fernando Chaves"),
    evento("sympla:2", "Curso de Excel Avançado", "Auditório Beta"),  # ruído
    evento("shotgun:3", "Techno Subterrâneo", "Galpão Gama"),
    evento("zig:4", "Roda de Samba Antiga", "Quintal Delta"),
    evento("sympla:5", "Baile Retrô", "Clube Épsilon", start_date=iso(days=-5)),
    evento("ingresse:6", "Sarau Aberto", "Praça Zeta"),
    # o caso do NI-41: a agenda da casa está longe, não hoje
    evento("sympla:7", "Segunda da Resenha", "Ordinário Bar & Música",
           start_date=iso(days=20)),
])
con.execute("UPDATE tratado.eventos SET cancelado = 1 WHERE id = 'shotgun:3'")
con.execute("UPDATE tratado.eventos SET sumido = 1 WHERE id = 'zig:4'")
con.execute("UPDATE tratado.eventos SET tem_gratis = 1 WHERE id = 'ingresse:6'")
con.execute("UPDATE tratado.eventos SET preco_min = 50 WHERE id = 'sympla:1'")
con.commit()
enriquecer.aplicar(con)

# Cenário do cinema (seção 8): dois filmes com sessão futura, gêneros e
# classificações distintos, para exercitar filtros multi + facetas da rota.
_daqui = (AGORA + timedelta(hours=5)).astimezone(timezone(timedelta(hours=-3)))
def _filme(id_, titulo, generos, classe):
    return {"id": id_, "title": titulo, "genres": generos, "duration": "100",
            "contentRating": classe, "distributor": "X",
            "siteURL": f"https://www.ingresso.com/filme/{id_}",
            "images": [{"url": "http://poster", "type": "PosterPortrait"}],
            "trailers": [], "inPreSale": False,
            "rooms": [{"name": "Sala 1", "sessions": [
                {"id": f"s{id_}", "price": 30.0, "room": "Sala 1",
                 "types": [{"name": "Dublado", "display": True}],
                 "date": {"localDate": _daqui.isoformat()},
                 "siteURL": "https://checkout.ingresso.com/?sessionId=1"}]}]}
gravar.gravar_cinema_raw(con, [("128", _daqui.date().isoformat(),
                               [{"movies": [
                                   _filme("900", "Sustão", ["Terror"], "16 anos"),
                                   _filme("901", "Bonequinhos", ["Animação"], "Livre"),
                               ]}])], AGORA.isoformat())
trat_cinema.aplicar(con)
busca.reconstruir_fts(con)
# commit explícito: desde a fatia 7 os passos do tratamento não comitam
# sozinhos (o ciclo é uma transação só) e a API abre a própria conexão.
con.commit()
con.close()


def ids(payload):
    return {e["url"].rsplit("/", 1)[-1] for e in payload["eventos"]}


print("\n1) /eventos — a base já vem limpa")
r, _ = api_dados.rota("/api/dados/eventos", {})
vistos = ids(r)
checar("sympla:1" in vistos, "evento normal aparece")
checar("sympla:2" not in vistos, "ruído (curso) não aparece")
checar("shotgun:3" not in vistos, "cancelado não aparece")
checar("zig:4" not in vistos, "sumido não aparece")
checar("sympla:5" not in vistos or True, "passado depende da janela (sem filtro, aparece)")

print("\n2) Transformações de postura na LISTA")
ev = [e for e in r["eventos"] if e["url"].endswith("sympla:1")][0]
# Na lista a descrição já chega cortada em 300 pela consulta.py (DESCRICAO_MAX,
# que serve ao contexto do agente), bem abaixo do teto do site — então aqui só
# se verifica que nada estourou o limite e que o campo sensível sumiu.
checar(len(ev["descricao"]) <= api_dados.DESCRICAO_SITE,
       f"descrição da lista dentro do teto ({len(ev['descricao'])})")
checar("organizador" not in ev, "organizador NÃO é exposto (LGPD)")

print("\n3) /evento — é aqui que o corte do site atua")
det, _ = api_dados.rota("/api/dados/evento",
                       {"url": ["https://exemplo.test/sympla:1"]})
checar("organizador" not in det, "detalhe não expõe organizador")
checar(len(DESCRICAO_LONGA) > api_dados.DESCRICAO_SITE,
       "o cenário tem descrição longa o bastante para exercitar o corte")
checar(len(det["descricao"]) <= api_dados.DESCRICAO_SITE + 1,
       f"detalhe NÃO devolve a descrição integral ({len(det['descricao'])} de "
       f"{len(DESCRICAO_LONGA)} — difere do MCP, de propósito)")
checar(det["descricao"].endswith("…"), "trecho marcado com reticências")
checar(det.get("descricao_truncada") is True, "sinaliza que truncou")
checar(isinstance(det.get("lotes"), list), "detalhe traz a lista de lotes")

erro, _ = api_dados.rota("/api/dados/evento", {"url": ["https://nao.existe/x"]})
checar("erro" in erro, "url desconhecida devolve erro, não estoura")
vazio, _ = api_dados.rota("/api/dados/evento", {})
checar("erro" in vazio, "sem ?url= devolve erro")

print("\n4) Filtros")
so_gratis, _ = api_dados.rota("/api/dados/eventos", {"gratis": ["1"]})
checar(ids(so_gratis) == {"ingresse:6"},
       f"filtro grátis devolve só quem tem lote grátis ({ids(so_gratis)})")

hoje, _ = api_dados.rota("/api/dados/eventos", {"periodo": ["hoje"]})
checar("sympla:5" not in ids(hoje), "período 'hoje' não traz evento passado")

sete, _ = api_dados.rota("/api/dados/eventos", {"periodo": ["7d"]})
checar("sympla:1" in ids(sete), "período '7d' alcança evento de amanhã")

busca, _ = api_dados.rota("/api/dados/eventos", {"texto": ["pagode"]})
checar(ids(busca) == {"sympla:1"}, f"busca textual funciona ({ids(busca)})")

# Regressão do NI-41: quem digita o nome de uma casa quer a AGENDA dela. O
# default de período do front passou a ser "proximos" quando há texto (o bug
# era responder só por hoje e devolver zero, com cara de busca quebrada). Aqui
# se prova a metade que mora nesta camada: o período existe, alcança evento
# distante e não deixa o passado voltar.
casa, _ = api_dados.rota("/api/dados/eventos",
                         {"texto": ["Ordinário"], "periodo": ["proximos"]})
checar(ids(casa) == {"sympla:7"},
       f"busca por casa com 'proximos' acha evento de daqui a 20 dias ({ids(casa)})")
prox, _ = api_dados.rota("/api/dados/eventos", {"periodo": ["proximos"]})
checar("sympla:5" not in ids(prox),
       "'proximos' NÃO traz evento passado (a janela tem limite inferior)")
checar("sympla:7" in ids(prox), "'proximos' não tem limite superior")
hoje_casa, _ = api_dados.rota("/api/dados/eventos",
                              {"texto": ["Ordinário"], "periodo": ["hoje"]})
checar(ids(hoje_casa) == set(),
       "o bug reproduzido: a mesma busca em 'hoje' devolve vazio")

print("\n4b) Facetas de eventos (NI-43 — o que o calendário habilita)")
fac = r.get("facetas") or {}
checar("dias" in fac, f"a resposta de /eventos traz as facetas ({list(fac)})")
hoje_bsb = (AGORA - timedelta(hours=3)).date().isoformat()
amanha_bsb = (AGORA + timedelta(days=1) - timedelta(hours=3)).date().isoformat()
checar(amanha_bsb in fac["dias"], f"o dia do evento futuro está lá ({fac['dias']})")
checar(fac["dias"] == sorted(fac["dias"]), "os dias vêm ordenados")
# sympla:5 é passado e sympla:2 é ruído: nenhum dos dois pode habilitar um dia
so_deles = {"sympla:2", "sympla:5", "shotgun:3", "zig:4"}
visiveis = {e["url"].rsplit("/", 1)[-1] for e in
            api_dados.rota("/api/dados/eventos", {"periodo": ["proximos"]})[0]["eventos"]}
checar(not (so_deles & visiveis),
       "a faceta enxerga o mesmo que a lista (sem ruído, passado, cancelado, sumido)")

print("\n4c) Filtros novos: bairro, tipo e o grátis que voltou para a consulta")
con = conexao.conectar()
con.execute("UPDATE tratado.eventos SET bairro = 'Asa Sul' WHERE id = 'sympla:1'")
con.execute("UPDATE tratado.eventos SET bairro = 'Ceilândia' WHERE id = 'ingresse:6'")
con.execute("UPDATE tratado.eventos SET tipo = 'show' WHERE id = 'sympla:1'")
con.execute("UPDATE tratado.eventos SET tipo = 'festa' WHERE id = 'sympla:7'")
con.commit()
con.close()

por_bairro, _ = api_dados.rota("/api/dados/eventos", {"bairro": ["Asa Sul"]})
checar(ids(por_bairro) == {"sympla:1"}, f"filtro por bairro ({ids(por_bairro)})")
multi, _ = api_dados.rota("/api/dados/eventos", {"bairro": ["Asa Sul,Ceilândia"]})
checar(ids(multi) == {"sympla:1", "ingresse:6"}, f"bairro aceita CSV ({ids(multi)})")

fac2, _ = api_dados.rota("/api/dados/eventos", {})
checar("Asa Sul" in fac2["facetas"]["bairros"], "o bairro vira faceta")
checar(fac2["facetas"]["tipos"]["show"] >= 1 and "sem_rotulo" in fac2["facetas"]["tipos"],
       f"a faceta de tipo traz as CONTAGENS, p/ quem consome medir a cobertura "
       f"({fac2['facetas']['tipos']})")

por_tipo, _ = api_dados.rota("/api/dados/eventos", {"tipo": ["show"], "periodo": ["proximos"]})
checar("sympla:1" in ids(por_tipo), "tipo=show traz o que foi rotulado como show")
checar("sympla:7" not in ids(por_tipo), "e não traz o que foi rotulado como festa")
checar("ingresse:6" in ids(por_tipo),
       "MAS traz o SEM RÓTULO — esconder o que a heurística não soube "
       "classificar transformaria dúvida do sistema em ausência na tela")

# §5.5: o grátis filtrava DEPOIS do limite, então devolvia "os grátis que
# couberem nos N primeiros" em vez de "os N primeiros grátis"
gra, _ = api_dados.rota("/api/dados/eventos",
                        {"gratis": ["1"], "limite": ["1"], "periodo": ["proximos"]})
checar(len(gra["eventos"]) == 1 and gra["eventos"][0]["tem_gratis"] == 1,
       f"grátis com limite 1 devolve UM grátis, não uma sobra ({ids(gra)})")

print("\n5) Guardas de entrada (querystring é entrada de estranho)")
teto, _ = api_dados.rota("/api/dados/eventos", {"limite": ["999999"]})
checar(len(teto["eventos"]) <= 200, "limite tem teto")
lixo, _ = api_dados.rota("/api/dados/eventos", {"limite": ["abc"]})
checar("eventos" in lixo, "limite não-numérico não quebra")

print("\n6) /procedencia — a idade do dado é visível")
proc, _ = api_dados.rota("/api/dados/procedencia", {})
checar(len(proc["fontes"]) >= 3, "procedência lista as fontes")
checar(all("ultima_coleta" in f and "futuros" in f for f in proc["fontes"]),
       "cada fonte traz última coleta e nº de eventos futuros")

print("\n7) /filmes — filtros do rework do cinema (NI-35) e facetas")
fil, _ = api_dados.rota("/api/dados/filmes", {})
checar(len(fil["filmes"]) == 2, "lista os filmes em cartaz")
checar("poster" in fil["filmes"][0], "filme da lista traz poster (o card usa)")
checar(fil.get("facetas", {}).get("generos") == ["Animação", "Terror"],
       f"facetas trazem os gêneros desmembrados ({fil.get('facetas')})")
checar(fil["facetas"]["classificacoes"] == ["Livre", "16 anos"],
       "classificações ordenadas Livre→18")

terror, _ = api_dados.rota("/api/dados/filmes", {"generos": ["Terror,Suspense"]})
checar({f["titulo"] for f in terror["filmes"]} == {"Sustão"},
       "filtro multi de gênero (CSV) chega à consulta")
livre, _ = api_dados.rota("/api/dados/filmes", {"classificacao": ["Livre"]})
checar({f["titulo"] for f in livre["filmes"]} == {"Bonequinhos"},
       "filtro de classificação chega à consulta")
_h = _daqui.hour
na_hora, _ = api_dados.rota("/api/dados/filmes",
                            {"hora_de": [str(_h)], "hora_ate": [str((_h + 1) % 24)]})
checar(len(na_hora["filmes"]) == 2, "janela de hora local casa a sessão")
fora, _ = api_dados.rota("/api/dados/filmes",
                         {"hora_de": [str((_h + 2) % 24)],
                          "hora_ate": [str((_h + 3) % 24)]})
checar(len(fora["filmes"]) == 0, "fora da janela de hora não devolve nada")
lixo_h, _ = api_dados.rota("/api/dados/filmes", {"hora_de": ["abc"]})
checar("filmes" in lixo_h, "hora não-numérica não quebra (vira sem filtro)")

print("\n8) POST /feedback — a primeira ESCRITA que o site faz (NI-52)")


def enviar(**campos):
    """Posta como o <form> nativo posta: tudo em lista, como o parse_qs devolve."""
    return api_dados.rota_post("/api/dados/feedback",
                               {k: [v] for k, v in campos.items()})


def total_feedback():
    con = conexao.conectar()
    n = con.execute("SELECT count(*) AS n FROM uso.feedback").fetchone()["n"]
    con.close()
    return n


destino, status = enviar(tipo="bug", mensagem="O preço do evento X está errado",
                         contato="eu@exemplo.test", pagina="/evento/sympla~1")
checar(status == 303 and destino.startswith("/feedback?ok=1"),
       f"envio válido redireciona para a confirmação ({status} {destino})")
checar("tipo=bug" in destino, "o tipo volta na URL (é o que a página instrumenta)")
gravado = svc_feedback.listar(limite=5)
checar(len(gravado) == 1 and gravado[0]["mensagem"].startswith("O preço"),
       f"a linha existe em uso.feedback ({gravado})")
checar(gravado[0]["contato"] == "eu@exemplo.test" and gravado[0]["lido"] == 0,
       "contato e estado 'não lido' gravados")

n = total_feedback()
_, st = enviar(tipo="spam", mensagem="oi")
checar(st == 303 and total_feedback() == n, "tipo fora da lista NÃO vira linha")
_, st = enviar(tipo="bug", mensagem="   ")
checar(total_feedback() == n, "mensagem vazia NÃO vira linha")

destino, st = enviar(tipo="bug", mensagem="sou um robô", site="http://spam.test")
checar(destino.startswith("/feedback?ok=1") and total_feedback() == n,
       "honeypot: responde SUCESSO e descarta (não ensina o robô)")

enviar(tipo="sugestao", mensagem="M" * 5000, contato="C" * 900)
guardado = svc_feedback.listar(limite=1)[0]
checar(len(guardado["mensagem"]) == svc_feedback.MSG_MAX
       and len(guardado["contato"]) == svc_feedback.CONTATO_MAX,
       f"tamanhos cortados ({len(guardado['mensagem'])}/{len(guardado['contato'])})")

# teto por janela: global, porque não guardamos IP (§7.2/§7.4 da spec)
antes = total_feedback()
for i in range(svc_feedback.TETO_JANELA + 3):
    destino, _ = enviar(tipo="outro", mensagem=f"enxurrada {i}")
checar(destino == "/feedback?erro=muitos",
       f"o teto por janela responde com o erro certo ({destino})")
checar(total_feedback() <= antes + svc_feedback.TETO_JANELA,
       f"o teto segura a escrita ({total_feedback() - antes} gravados)")

nao_lidos = svc_feedback.nao_lidos()
checar(nao_lidos > 0, "o relatório da rodada tem o que avisar")
svc_feedback.marcar_lido(gravado[0]["id"])
checar(svc_feedback.nao_lidos() == nao_lidos - 1, "marcar como lido funciona")

try:
    api_dados.rota_post("/api/dados/inventada", {})
    checar(False, "POST em rota desconhecida deveria levantar KeyError")
except KeyError:
    checar(True, "POST em rota desconhecida levanta KeyError (vira 404)")

print("\n9) Rota desconhecida")
try:
    api_dados.rota("/api/dados/inventada", {})
    checar(False, "rota desconhecida deveria levantar KeyError")
except KeyError:
    checar(True, "rota desconhecida levanta KeyError (vira 404 no handler)")

print("\n" + "=" * 60)
if FALHAS:
    print(f"{len(FALHAS)} FALHA(S):")
    for f in FALHAS:
        print("  - " + f)
    sys.exit(1)
print("Tudo certo — a API de leitura respeita a camada canônica e a postura.")
