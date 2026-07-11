"""Teste executável do enriquecimento v1 (ruído + dedupe) e do seu efeito na
camada de consulta. Usa o banco descartável eventos_teste no Neon (não toca a
base de produção — ver tests/base_teste.py).

Uso: python tests/test_enriquecer.py
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import store  # noqa: E402
import enriquecer  # noqa: E402
import consulta  # noqa: E402

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
        "SELECT id, ruido, ruido_motivo, dedupe_grupo, dedupe_canonico "
        "FROM eventos ORDER BY id").fetchall()


def linha(con, ev_id):
    return con.execute("SELECT * FROM eventos WHERE id = %s", (ev_id,)).fetchone()


def main():
    con = store.conectar()
    store.upsert_eventos(con, EVENTOS)
    resultado = enriquecer.aplicar(con)
    store.reconstruir_fts(con)

    # --- ruído ---
    marcados = {r["id"] for r in con.execute(
        "SELECT id FROM eventos WHERE ruido = 1")}
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

    # --- idempotência: aplicar de novo não muda nada ---
    antes = dump(con)
    enriquecer.aplicar(con)
    assert dump(con) == antes
    print("idempotência: aplicar 2x = mesmo estado — ok")

    # --- consulta: ruído e não-canônicos somem; outras_urls aparece ---
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

    # --- campos ricos: re-upsert do catálogo (sem descrição) não zera a colhida ---
    store.upsert_eventos(con, [evento(id="sympla:desc2", nome="Evento Descrito",
                                      descricao="texto original")])
    store.upsert_eventos(con, [evento(id="sympla:desc2", nome="Evento Descrito")])
    assert linha(con, "sympla:desc2")["descricao"] == "texto original"
    store.upsert_eventos(con, [evento(id="sympla:desc2", nome="Evento Descrito",
                                      descricao="texto novo")])
    assert linha(con, "sympla:desc2")["descricao"] == "texto novo"
    print("campos ricos: upsert preserva descrição já colhida (COALESCE) — ok")

    con.close()
    print("\nOK — enriquecimento v1 e consulta se comportam como a spec pede.")


if __name__ == "__main__":
    main()
