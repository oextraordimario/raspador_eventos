"""Teste executável do enriquecimento v1 (ruído + dedupe) e do seu efeito na
camada de consulta. Usa o banco descartável eventos_teste no Neon (não toca a
base de produção — ver tests/base_teste.py).

Uso: python tests/test_enriquecer.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from base import conexao
from tratamento import busca
from tratamento import comum
from tratamento import enriquecer  # noqa: E402
from servico import consulta  # noqa: E402

import base_teste  # noqa: E402

# Redireciona a base para o banco descartável antes de qualquer conectar().
base_teste.preparar()

_SEQ = 0


def evento(**kw):
    """Evento normalizado com defaults preenchidos (como os scrapers geram)."""
    global _SEQ
    _SEQ += 1
    e = {
        "fonte": "sympla", "nome": f"Evento {_SEQ}",
        "start_date": "2026-07-11T22:00:00+00:00", "end_date": None,
        "cidade": "Brasília", "estado": "DF", "local_nome": None,
        "endereco": None, "lat": None, "lon": None, "categoria": None,
        "organizador": None, "url": f"https://exemplo.com/{_SEQ}",
        "imagem": None, "raspado_em": "2026-07-09T00:00:00+00:00",
    }
    e.update(kw)
    e.setdefault("id_nativo", str(1000 + _SEQ))
    e.setdefault("id", f"{e['fonte']}:{e['id_nativo']}")
    return e


EVENTOS = [
    # --- ruído: deve marcar ---
    evento(id="sympla:r1", nome="Conecte-se com a Melhor Banda Larga Residencial em Brasília"),
    evento(id="sympla:r2", nome="Curso de Fotografia Noturna"),
    evento(id="sympla:r3", nome="Imersão em Vendas 2026"),  # acento no termo
    evento(id="sympla:r4", nome="Festa de Lançamento - Pré-Candidatura Deputada"),
    # --- ruído: NÃO deve marcar (fronteira de palavra / termo perigoso) ---
    evento(id="sympla:ok1", nome="Percurso do Samba"),
    evento(id="sympla:ok2", nome="Aulão de Dança + Baile"),
    evento(id="sympla:ok3", nome="Lançamento do Álbum 'O Mago' em Brasília"),
    # --- dedupe: par verdadeiro (mesmo dia, mesmo local, nome parecido) ---
    evento(id="sympla:d1", fonte="sympla", nome="Baile do Menos é Mais",
           local_nome="Arena BRB", endereco="SRPN Trecho 3", organizador="R2",
           imagem="https://img/x.jpg", url="https://sympla/baile"),
    evento(id="shotgun:d2", fonte="shotgun", nome="Baile do Menos é Mais - Brasília",
           local_nome="Arena BRB", url="https://shotgun/baile"),
    # --- dedupe: falso-positivo real da base (mesmo dia, locais diferentes,
    #     nomes que só compartilham "Oitavas de Final") — NÃO pode agrupar ---
    evento(id="sympla:f1", fonte="sympla", local_nome="Varanda",
           nome="Varanda da Copa | Oitavas de Final + Pagode & Feijoada"),
    evento(id="shotgun:f2", fonte="shotgun", local_nome="Setor Comercial Sul",
           nome="05/07 Samba Da Passarinha (Oitavas De Final Copa)"),
    # --- dedupe: dias diferentes nunca agrupam, mesmo nome idêntico ---
    evento(id="sympla:s1", fonte="sympla", nome="Sarau do Cerrado",
           start_date="2026-07-11T22:00:00+00:00"),
    evento(id="shotgun:s2", fonte="shotgun", nome="Sarau do Cerrado",
           start_date="2026-07-18T22:00:00.000Z"),  # formato Shotgun
    # --- campos ricos: termo de busca que SÓ existe na descrição ---
    evento(id="sympla:desc1", nome="Vórtice na Capital",
           url="https://exemplo.com/desc",
           descricao="Noite de música eletrônica com DJs convidados até o amanhecer."),
]


def dump(con):
    return con.execute(
        "SELECT id, ruido, ruido_motivo, dedupe_grupo, dedupe_canonico, tipo "
        "FROM tratado.eventos ORDER BY id").fetchall()


def linha(con, ev_id):
    return con.execute("SELECT * FROM tratado.eventos WHERE id = %s", (ev_id,)).fetchone()


def main():
    con = conexao.conectar()
    comum.upsert_eventos(con, EVENTOS)
    resultado = enriquecer.aplicar(con)
    busca.reconstruir_fts(con)

    # --- ruído ---
    marcados = {r["id"] for r in con.execute(
        "SELECT id FROM tratado.eventos WHERE ruido = 1")}
    assert marcados == {"sympla:r1", "sympla:r2", "sympla:r3", "sympla:r4"}, marcados
    assert linha(con, "sympla:r1")["ruido_motivo"] == "banda larga"
    assert linha(con, "sympla:r3")["ruido_motivo"] == "imersao"
    assert len(resultado["ruido"]) == 4
    print("ruído: 4 marcados (banda larga/curso/imersão/candidatura), "
          "'Percurso'/'Aulão'/lançamento de álbum intactos — ok")

    # --- dedupe: par verdadeiro agrupado, canônico = mais completo (sympla) ---
    d1, d2 = linha(con, "sympla:d1"), linha(con, "shotgun:d2")
    assert d1["dedupe_grupo"] == "sympla:d1" == d2["dedupe_grupo"], \
        (dict(d1), dict(d2))
    assert d1["dedupe_canonico"] == 1 and d2["dedupe_canonico"] == 0
    print("dedupe: par verdadeiro agrupado, canônico pelo mais completo — ok")

    # --- dedupe: falso-positivo e dias diferentes seguem separados ---
    for ev_id in ("sympla:f1", "shotgun:f2", "sympla:s1", "shotgun:s2"):
        r = linha(con, ev_id)
        assert r["dedupe_grupo"] is None and r["dedupe_canonico"] == 1, \
            (ev_id, dict(r))
    print("dedupe: falso-positivo ('Oitavas de Final') e dias distintos "
          "não agrupam — ok")

    # --- tipo (NI-44): festa × show, e o TERCEIRO estado ---
    tipos = {r["id"]: r["tipo"] for r in con.execute(
        "SELECT id, tipo FROM tratado.eventos")}
    assert tipos["shotgun:d2"] == "festa", tipos["shotgun:d2"]   # "Baile do..."
    assert tipos["sympla:s1"] == "show", tipos["sympla:s1"]      # "Sarau do..."
    # sem palavra que decida, NULL — e NULL aqui é rótulo ausente de propósito,
    # não falha: o princípio é errar para o lado de não esconder festa real
    assert tipos["sympla:desc1"] is None, tipos["sympla:desc1"]
    assert resultado["tipos"]["festa"] >= 1 and resultado["tipos"]["show"] >= 1
    # contradição entre categoria e nome não vira rótulo (o caso em que um
    # palpite teria mais chance de estar errado)
    assert enriquecer._classificar_tipo("Festa do Vinil", "shows") is None
    assert enriquecer._classificar_tipo("Noite Qualquer", None) is None
    print("tipo: festa/show por palavra no nome, contradição e silêncio → NULL — ok")

    # o filtro por tipo NÃO pode esconder o sem-rótulo
    con.commit()
    so_show = {e["id"] for e in consulta.buscar_eventos(tipo="show", limite=100)}
    assert "sympla:s1" in so_show and "sympla:desc1" in so_show, so_show
    assert "shotgun:d2" not in so_show, so_show
    print("consulta: tipo=show traz os shows E os sem rótulo, não as festas — ok")

    # --- idempotência: aplicar de novo não muda nada ---
    antes = dump(con)
    enriquecer.aplicar(con)
    assert dump(con) == antes
    print("idempotência: aplicar 2x = mesmo estado — ok")

    # --- a guarda que a arquitetura exige: reconstruir a prata NÃO pode zerar
    #     `tipo`. É o teste que pega o dia em que alguém puser a coluna em
    #     comum.COLS_EVENTO, que é reescrita inteira a cada reconstrução. ---
    comum.upsert_eventos(con, EVENTOS)
    depois = {r["id"]: r["tipo"] for r in con.execute(
        "SELECT id, tipo FROM tratado.eventos")}
    assert depois == tipos, \
        ("upsert_eventos zerou `tipo` — a coluna é do enriquecer e NÃO pode "
         "entrar em COLS_EVENTO", {k: v for k, v in depois.items() if tipos[k] != v})
    print("fronteira: upsert do catálogo não apaga o `tipo` do enriquecer — ok")

    # --- consulta: ruído e não-canônicos somem; outras_urls aparece ---
    # commit explícito: desde a fatia 7 os passos do tratamento não comitam
    # sozinhos (o ciclo é uma transação só) e a consulta abre a própria conexão.
    con.commit()
    todos = consulta.buscar_eventos(limite=100)
    ids = {e["url"] for e in todos}
    nomes = [e["nome"] for e in todos]
    assert "Conecte-se com a Melhor Banda Larga Residencial em Brasília" not in nomes
    assert "Curso de Fotografia Noturna" not in nomes
    assert "https://shotgun/baile" not in ids, "membro não-canônico vazou"
    baile = [e for e in todos if e["url"] == "https://sympla/baile"]
    assert len(baile) == 1, "canônico deveria aparecer exatamente 1x"
    assert baile[0]["outras_urls"] == "https://shotgun/baile", baile[0]
    sem_grupo = [e for e in todos if e["nome"] == "Percurso do Samba"]
    assert sem_grupo and sem_grupo[0]["outras_urls"] is None
    print("consulta: ruído/duplicata escondidos, outras_urls do grupo — ok")

    # --- consulta: incluir_ruido=True devolve tudo (depuração) ---
    com_ruido = consulta.buscar_eventos(limite=100, incluir_ruido=True)
    assert len(com_ruido) == len(todos) + 4
    print("consulta: incluir_ruido=True devolve os marcados — ok")

    # --- campos ricos: FTS acha termo que só está na descrição (com acento) ---
    achados = consulta.buscar_eventos(texto="eletrônica", limite=10)
    assert any(e["url"] == "https://exemplo.com/desc" for e in achados), achados
    trecho = [e for e in achados if e["url"] == "https://exemplo.com/desc"][0]
    assert trecho["descricao"].startswith("Noite de música eletrônica")
    print("campos ricos: FTS acha pelo texto da descrição, retorno traz trecho — ok")

    # --- o upsert escreve o que recebe, inclusive NULL (sem COALESCE) ---
    # Isto MUDOU na fatia 7, e é o ponto do desenho novo. Antes o upsert usava
    # COALESCE em descricao/atracoes/preco_min/categoria, porque a escrita da
    # prata era PARCIAL: o catálogo escrevia umas colunas e o "descrever"
    # outras, e sem o COALESCE a raspagem seguinte zerava o que já tinha sido
    # colhido. Só que COALESCE protege contra valor novo NULL e não contra
    # valor novo genérico — foi exatamente assim que o `event_type` = 'NORMAL'
    # do Sympla destruiu a categoria boa de 206 eventos a cada rodada (§6.2).
    #
    # Hoje a escrita é INTEIRA e vem toda do cru: quem preserva a descrição já
    # colhida é a camada cru, que guarda o payload de detalhe para sempre
    # (tests/test_bronze.py cobre isso). Preservar por COALESCE aqui esconderia
    # bug de reconstrução em vez de evitá-lo.
    comum.upsert_eventos(con, [evento(id="sympla:desc2", nome="Evento Descrito",
                                      descricao="texto original")])
    comum.upsert_eventos(con, [evento(id="sympla:desc2", nome="Evento Descrito")])
    assert linha(con, "sympla:desc2")["descricao"] is None, \
        "o upsert não pode mais preservar valor antigo: a verdade é o cru"
    comum.upsert_eventos(con, [evento(id="sympla:desc2", nome="Evento Descrito",
                                      descricao="texto novo")])
    assert linha(con, "sympla:desc2")["descricao"] == "texto novo"
    print("upsert: escreve a linha INTEIRA, sem COALESCE (a verdade é o cru) — ok")

    con.commit()
    con.close()
    print("\nOK — enriquecimento v1 e consulta se comportam como a spec pede.")


if __name__ == "__main__":
    main()
