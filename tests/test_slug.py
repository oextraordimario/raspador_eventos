"""Teste executável do endereçamento público: título limpo, slugificação e a
escada de desempate que garante endereço único (spec 20260729_urls-semanticas).

Duas metades, e a divisão é de propósito:

  1. as funções PURAS de `base/texto.py` — rodam sem banco nenhum;
  2. o passo `tratamento/slug.py` contra o banco descartável eventos_teste no
     Neon (ver tests/base_teste.py), onde vivem a escada, a idempotência e a
     estabilidade sob reconstrução.

A segunda metade é a que importa: um slug que muda de rodada em rodada é um
link compartilhado que morre, e o teste é o que prova que não muda.

Uso: python tests/test_slug.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from base import texto  # noqa: E402

falhas = []


def checar(cond, msg):
    print(f"  {'ok  ' if cond else 'FALHA'} {msg}")
    if not cond:
        falhas.append(msg)


def igual(obtido, esperado, msg):
    checar(obtido == esperado, f"{msg} (obtido {obtido!r}, esperado {esperado!r})")


# ── 1. título limpo (NI-33) ────────────────────────────────────────────────
#
# Os casos vêm de nomes REAIS da base (sondagem de 2026-07-29), não de exemplos
# inventados: é o que garante que a regra foi calibrada contra o que as fontes
# publicam de verdade.
print("\n1) titulo_limpo — remove data isolada, preserva número que é nome")

igual(texto.titulo_limpo("Forró na Varanda | 28.07 | Varanda do Contexto"),
      "Forró na Varanda | Varanda do Contexto",
      "segmento que é só data sai; o resto do título fica")
igual(texto.titulo_limpo("28/07 - Festa da Firma"), "Festa da Firma",
      "data no começo, cercada por separador")
igual(texto.titulo_limpo("Festa da Firma - 28/07"), "Festa da Firma",
      "data no fim, cercada por separador")

# A regra CONSERVADORA: número que faz parte do nome não pode ser confundido
# com data. Falso positivo aqui estraga o título de uma festa real, e é por
# isso que a regra exige separador isolando o trecho.
for nome in ("Rock dos 80/90", "Baile 24/7", "Aniversário 10/10 anos",
             "Galpão 17 Rock Festival", "Pop-Rock com Conecta"):
    igual(texto.titulo_limpo(nome), nome, f"não mexe em {nome!r}")

igual(texto.titulo_limpo("11/07"), "11/07",
      "nome que é SÓ data devolve o original (título vazio seria pior)")

# O separador do autor é PRESERVADO. A primeira versão remontava tudo com
# " | " fixo: invisível quando a regra só pintava a tela, e degradação de dado
# quando ela passou a escrever na base (125 nomes alterados na primeira rodada,
# a maioria só trocando travessão por barra).
igual(texto.titulo_limpo("Bernardo Rosa Trio — O melhor do Pop Rock"),
      "Bernardo Rosa Trio — O melhor do Pop Rock",
      "travessão não vira barra quando não há data para remover")
igual(texto.titulo_limpo("Galpão 17 – 8 Anos | Dave Evans"),
      "Galpão 17 – 8 Anos | Dave Evans",
      "cada separador fica como o autor escreveu")
igual(texto.titulo_limpo("Festa – 28.07 – Casa Volpi"), "Festa – Casa Volpi",
      "com a data no meio, sobra UM separador, e é o do autor")
igual(texto.titulo_limpo(None), None, "None atravessa sem explodir")
igual(texto.titulo_limpo(""), "", "vazio atravessa sem explodir")


# ── 2. slugificação ────────────────────────────────────────────────────────
print("\n2) slugificar — sem acento, minúsculo, só [a-z0-9-]")

igual(texto.slugificar("Forró na Varanda"), "forro-na-varanda", "acento")
igual(texto.slugificar("Roça N' Roll"), "roca-n-roll", "cedilha e apóstrofo")
igual(texto.slugificar("Blood fire death festival 11° edição 2026"),
      "blood-fire-death-festival-11-edicao-2026", "símbolo vira separador")
igual(texto.slugificar("  --Festa!!  da   Firma--  "), "festa-da-firma",
      "pontuação colapsa e as pontas ficam limpas")
igual(texto.slugificar("Homem-Aranha: Um Novo Dia"), "homem-aranha-um-novo-dia",
      "dois-pontos do título de filme")
igual(texto.slugificar("🔥🔥"), "",
      "entrada sem caractere aproveitável devolve vazio (quem chama decide)")
igual(texto.slugificar(None), "", "None devolve vazio")

# Teto: corta recuando até a fronteira de palavra.
longo = ("Laboratório PSY: PsyLab Samambaia — desvendando vertentes e "
         "fortalecendo a cena eletrônica local")
s = texto.slugificar(longo, teto=60)
checar(len(s) <= 60, f"teto respeitado ({len(s)} chars)")
checar(not s.endswith("-"), "corte não deixa hífen na ponta")
checar(s == "laboratorio-psy-psylab-samambaia-desvendando-vertentes-e",
       f"corta na fronteira de palavra ({s!r})")
igual(texto.slugificar("abcdefghij", teto=4), "abcd",
      "sem fronteira de palavra útil, corta seco")


# ── 3. o passo do ciclo, contra a base ─────────────────────────────────────
#
# Daqui para baixo precisa de banco: a escada de desempate só existe em relação
# ao que já foi atribuído, e a estabilidade só se prova rodando duas vezes.
from base import conexao  # noqa: E402
from servico import consulta  # noqa: E402
from tratamento import comum, slug  # noqa: E402

import base_teste  # noqa: E402

base_teste.preparar()

_SEQ = 0


def evento(nome, dia, **kw):
    """Evento normalizado, como as trilhas de tratamento produzem."""
    global _SEQ
    _SEQ += 1
    e = {"fonte": "sympla", "id_nativo": str(1000 + _SEQ),
         "nome": nome, "start_date": f"{dia}T22:00:00-03:00", "end_date": None,
         "cidade": "Brasília", "estado": "DF", "local_nome": "Casa Alfa",
         "endereco": None, "lat": None, "lon": None, "categoria": None,
         "organizador": None, "url": f"https://exemplo.com/{_SEQ}",
         "imagem": None, "raspado_em": "2026-07-29T00:00:00+00:00"}
    e.update(kw)
    e.setdefault("id", f"{e['fonte']}:{e['id_nativo']}")
    return e


def slugs(con, tabela="tratado.eventos"):
    return {r["id"]: r["slug"] for r in
            con.execute(f"SELECT id, slug FROM {tabela}")}


con = conexao.conectar()

print("\n3) escada de desempate")

# Duas cópias do MESMO evento no mesmo dia (o caso real: 4 linhas de "Festa
# Junina | Roça N' Roll" em 31/07, uma canônica). O endereço limpo tem que ficar
# com o canônico — que é o que o site linka.
comum.upsert_eventos(con, [
    evento("Festa Junina", "2026-08-15", id="sympla:canon"),
    evento("Festa Junina", "2026-08-15", id="sympla:dup"),
])
con.execute("UPDATE tratado.eventos SET dedupe_canonico = 0, "
            "dedupe_grupo = 'sympla:canon' WHERE id = 'sympla:dup'")
con.execute("UPDATE tratado.eventos SET dedupe_grupo = 'sympla:canon' "
            "WHERE id = 'sympla:canon'")
slug.aplicar(con)
s = slugs(con)
igual(s["sympla:canon"], "festa-junina-15-08", "o CANÔNICO leva o endereço limpo")
igual(s["sympla:dup"], "festa-junina-15-08-2", "a duplicata leva o ordinal")

# A ordenação por INSTANTE (e não por dia) foi um bug de verdade na primeira
# rodada: as cópias têm horas diferentes, e o canônico levava o `-2`.
comum.upsert_eventos(con, [
    evento("Baile do Dia", "2026-08-16", id="sympla:tarde",
           start_date="2026-08-16T18:00:00-03:00"),
    evento("Baile do Dia", "2026-08-16", id="sympla:noite",
           start_date="2026-08-16T23:30:00-03:00"),
])
con.execute("UPDATE tratado.eventos SET dedupe_canonico = 0 "
            "WHERE id = 'sympla:tarde'")
slug.aplicar(con)
s = slugs(con)
igual(s["sympla:noite"], "baile-do-dia-16-08",
      "canônico da NOITE ganha do não-canônico da tarde (ordena por DIA)")

# Mesmo nome, mesmo dia-mês, ANOS diferentes: o ano desempata, e é legível.
comum.upsert_eventos(con, [
    evento("Aniversário da Casa", "2026-09-10", id="sympla:ano26"),
    evento("Aniversário da Casa", "2027-09-10", id="sympla:ano27"),
])
slug.aplicar(con)
s = slugs(con)
igual(s["sympla:ano26"], "aniversario-da-casa-10-09",
      "o mais ANTIGO fica com o endereço limpo (o passado não se move)")
igual(s["sympla:ano27"], "aniversario-da-casa-10-09-2027",
      "o do ano seguinte leva o ANO, não um ordinal")

# Nome sem nenhum caractere aproveitável cai no id.
comum.upsert_eventos(con, [evento("🔥🔥", "2026-09-11", id="sympla:emoji")])
slug.aplicar(con)
checar(slugs(con)["sympla:emoji"].startswith("sympla-"),
       f"nome só com emoji cai no id ({slugs(con)['sympla:emoji']!r})")

print("\n4) estabilidade — a propriedade que faz o link não morrer")

antes = slugs(con)
slug.aplicar(con)
igual(slugs(con), antes, "rodar duas vezes não muda NENHUM slug (idempotente)")

# Evento novo entrando não pode roubar o endereço de quem já tinha.
comum.upsert_eventos(con, [evento("Festa Junina", "2027-08-15", id="sympla:futuro")])
slug.aplicar(con)
s = slugs(con)
igual(s["sympla:canon"], "festa-junina-15-08",
      "homônimo de 2027 NÃO rouba o endereço do evento de 2026")
igual(s["sympla:futuro"], "festa-junina-15-08-2027",
      "o que chegou depois é que ganha o sufixo")

print("\n5) unicidade garantida pelo banco, não por convenção")

n = con.execute("SELECT count(*) tot, count(DISTINCT slug) uni "
                "FROM tratado.eventos").fetchone()
igual(n["tot"], n["uni"], "todo evento tem endereço único")
# SAVEPOINT, e não rollback: o upsert do tratamento não comita (quem comita é o
# ciclo), então um `con.rollback()` aqui levaria embora TODO o cenário montado
# acima — foi exatamente o que aconteceu na primeira versão deste teste.
try:
    with con.transaction():
        con.execute("UPDATE tratado.eventos SET slug = 'festa-junina-15-08' "
                    "WHERE id = 'sympla:dup'")
    checar(False, "índice único deveria ter barrado o slug duplicado")
except Exception:
    checar(True, "índice único barra slug duplicado (erro do banco, não silêncio)")

print("\n6) filmes")

con.execute(
    "INSERT INTO tratado.filmes (id, titulo, ano) VALUES "
    "('501', 'Homem-Aranha: Um Novo Dia', 2026), ('502', 'Mil Luas', NULL), "
    "('503', 'A Odisseia', 2026), ('504', 'A Odisseia', 2026) "
    "ON CONFLICT (id) DO NOTHING")
slug.aplicar(con)
sf = slugs(con, "tratado.filmes")
igual(sf["501"], "homem-aranha-um-novo-dia-2026", "título + ano (padrão IMDB)")
igual(sf["502"], "mil-luas", "sem ano do TMDB, o slug fica só com o título")
igual(sf["503"], "a-odisseia-2026", "primeiro do mesmo título+ano leva o limpo")
igual(sf["504"], "a-odisseia-2026-2", "o segundo leva ordinal")

r = consulta.sessoes_filme("mil-luas", con=con)
igual(r.get("slug"), "mil-luas", "resolve pelo slug exato")
con.execute("UPDATE tratado.filmes SET ano = 2026 WHERE id = '502'")
slug.aplicar(con)
r = consulta.sessoes_filme("mil-luas", con=con)
igual(r.get("slug"), "mil-luas-2026",
      "slug CURTO ainda resolve depois de o TMDB trazer o ano (link não morre)")

print("\n7) renome — o histórico de endereços (operacao.slugs)")

# 2,3% dos eventos trocam de nome durante a vida. É o único risco de verdade da
# spec, e é este teste que prova que o link compartilhado sobrevive.
antigo = slugs(con)["sympla:canon"]
con.execute("UPDATE tratado.eventos SET nome = 'Festa Junina | Parte 2' "
            "WHERE id = 'sympla:canon'")
slug.aplicar(con)
novo = slugs(con)["sympla:canon"]
checar(novo != antigo, f"o renome mudou o endereço ({antigo!r} -> {novo!r})")
r = consulta.detalhar_evento(antigo, con=con)
igual(r.get("id"), "sympla:canon", "o endereço ANTIGO ainda acha o evento")
igual(r.get("slug"), novo, "e devolve o endereço de hoje (o front responde 308)")

# Histórico apontando para registro que saiu da base tem que virar 404, e não
# um 308 para o nada — é por isso que o filtro está na view.
con.execute("INSERT INTO operacao.slugs (slug, entidade, registro_id, visto_em) "
            "VALUES ('fantasma-01-01', 'eventos', 'sympla:naoexiste', "
            "'2026-07-01T00:00:00+00:00') ON CONFLICT (slug) DO NOTHING")
checar("erro" in consulta.detalhar_evento("fantasma-01-01", con=con),
       "endereço cujo registro sumiu da base dá erro, não redireciona")

con.rollback()
con.close()

print("\n" + ("FALHOU: " + "; ".join(falhas) if falhas else "todos os testes passaram"))
sys.exit(1 if falhas else 0)
