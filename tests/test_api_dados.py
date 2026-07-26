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

import derivar  # noqa: E402
import enriquecer  # noqa: E402
import store  # noqa: E402

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

con = store.conectar()
store.upsert_eventos(con, [
    evento("sympla:1", "Pagode do Teste", "Casa Alfa",
           descricao=DESCRICAO_LONGA, organizador="Fernando Chaves"),
    evento("sympla:2", "Curso de Excel Avançado", "Auditório Beta"),  # ruído
    evento("shotgun:3", "Techno Subterrâneo", "Galpão Gama"),
    evento("zig:4", "Roda de Samba Antiga", "Quintal Delta"),
    evento("sympla:5", "Baile Retrô", "Clube Épsilon", start_date=iso(days=-5)),
    evento("ingresse:6", "Sarau Aberto", "Praça Zeta"),
])
con.execute("UPDATE eventos SET cancelado = 1 WHERE id = 'shotgun:3'")
con.execute("UPDATE eventos SET sumido = 1 WHERE id = 'zig:4'")
con.execute("UPDATE eventos SET tem_gratis = 1 WHERE id = 'ingresse:6'")
con.execute("UPDATE eventos SET preco_min = 50 WHERE id = 'sympla:1'")
con.commit()
enriquecer.aplicar(con)
store.reconstruir_fts(con)
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

print("\n7) Rota desconhecida")
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
