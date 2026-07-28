"""CLI mínima de curadoria — a ferramenta que torna a camada `curado` usável.

Sem ela, `curado.correcoes` seria uma tabela que só o DBeaver alimenta, e uma
correção sem motivo obrigatório vira mistério em três meses.

Uso (da raiz do repo):
    python src/ferramentas/curar.py pendencias [--tipo local-desconhecido]
    python src/ferramentas/curar.py corrigir <id> --campo nome --valor "X" \
        --motivo "a fonte grafou errado" [--autor mario]
    python src/ferramentas/curar.py ativas [<id>]
    python src/ferramentas/curar.py revogar <n-da-correcao> --motivo "..."
    python src/ferramentas/curar.py local <nome> [--alias A --alias B] [--fora-df]

A correção NÃO é aplicada na hora: ela é reaplicada por tratamento/curadoria.py
ao fim de toda rodada, depois do enriquecer e antes do FTS. Para ver o efeito
agora, rode `python src/pipeline/atualizar.py --so-enriquecer`.

A evolução natural — e provavelmente o fim lógico num produto que É um agente —
é curar conversando, por uma tool MCP de escrita. Fica fora desta spec porque
muda o modelo de segurança do MCP remoto, hoje somente-leitura.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from base import conexao          # noqa: E402
from tratamento import curadoria  # noqa: E402


def _agora():
    return datetime.now(timezone.utc).isoformat()


def _slug(texto):
    t = unicodedata.normalize("NFD", (texto or "").casefold())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "local"


def cmd_pendencias(con, args):
    itens = curadoria.pendencias(con)
    if args.tipo:
        itens = [i for i in itens if i["tipo"] == args.tipo]
    if not itens:
        print("Nada pendente.")
        return
    por_tipo = {}
    for i in itens:
        por_tipo.setdefault(i["tipo"], []).append(i)
    for tipo, lista in sorted(por_tipo.items()):
        print(f"\n=== {tipo}  ({len(lista)}) ===")
        print(f"  {lista[0]['porque']}\n")
        for i in lista[:args.limite]:
            print(f"  {i['registro_id']:<34} {(i['detalhe'] or '')[:60]}")
        if len(lista) > args.limite:
            print(f"  … e mais {len(lista) - args.limite} "
                  f"(--limite para ver mais)")


def cmd_corrigir(con, args):
    if len(args.campo) != len(args.valor):
        sys.exit("--campo e --valor têm que vir em pares")
    valores = dict(zip(args.campo, args.valor))
    curadoria.validar(valores)          # levanta se sair da allowlist
    atual = con.execute("SELECT * FROM tratado.eventos WHERE id = %s",
                        (args.registro_id,)).fetchone()
    if not atual:
        sys.exit(f"nenhum evento com id {args.registro_id!r} em tratado.eventos")
    antes = {c: (str(atual[c]) if atual[c] is not None else None)
             for c in valores}
    con.execute(
        "INSERT INTO curado.correcoes (entidade, registro_id, valores, "
        "valores_antes, motivo, autor, criado_em) "
        "VALUES ('eventos', %s, %s, %s, %s, %s, %s)",
        (args.registro_id, json.dumps(valores, ensure_ascii=False),
         json.dumps(antes, ensure_ascii=False), args.motivo, args.autor,
         _agora()))
    con.commit()
    print(f"correção registrada para {args.registro_id}:")
    for c, v in valores.items():
        print(f"  {c}: {antes[c]!r} -> {v!r}")
    print(f"  motivo: {args.motivo}")
    print("\nEla é aplicada ao fim da próxima rodada. Para ver agora:")
    print("  python src/pipeline/atualizar.py --so-enriquecer")


def cmd_ativas(con, args):
    sql = ("SELECT id, registro_id, valores, motivo, autor, criado_em "
           "FROM curado.correcoes WHERE revogada_em IS NULL")
    params = []
    if args.registro_id:
        sql += " AND registro_id = %s"
        params.append(args.registro_id)
    linhas = con.execute(sql + " ORDER BY id", params).fetchall()
    if not linhas:
        print("Nenhuma correção ativa.")
        return
    for r in linhas:
        v = r["valores"]
        v = json.loads(v) if isinstance(v, str) else v
        print(f"#{r['id']:<4} {r['registro_id']:<34} {r['criado_em'][:10]} "
              f"[{r['autor']}]")
        print(f"      {v}")
        print(f"      motivo: {r['motivo']}")


def cmd_revogar(con, args):
    cur = con.execute(
        "UPDATE curado.correcoes SET revogada_em = %s "
        "WHERE id = %s AND revogada_em IS NULL", (_agora(), args.numero))
    con.commit()
    if not cur.rowcount:
        sys.exit(f"correção #{args.numero} não existe ou já foi revogada")
    # Revogar preenche revogada_em; a linha NUNCA é apagada — histórico de
    # decisão humana é tão insubstituível quanto dado bruto.
    print(f"correção #{args.numero} revogada (a linha continua na tabela).")


def cmd_local(con, args):
    con.execute(
        "INSERT INTO curado.locais (id, nome, aliases, no_df, autor, "
        "criado_em) VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET nome = excluded.nome, "
        "  aliases = excluded.aliases, no_df = excluded.no_df, "
        "  atualizado_em = excluded.criado_em",
        (_slug(args.nome), args.nome, args.alias or [], not args.fora_df,
         args.autor, _agora()))
    con.commit()
    print(f"local canônico: {args.nome} (id {_slug(args.nome)}, "
          f"no_df={not args.fora_df}, aliases={args.alias or []})")
    if not args.fora_df:
        print("\nMudar a lista NÃO recupera o passado: o recorte roda na "
              "coleta.\nRode o Ticket and Go para trazer os eventos desta "
              "casa (~3 min):\n  python src/pipeline/atualizar.py")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("pendencias", help="o que precisa de olho humano")
    q.add_argument("--tipo")
    q.add_argument("--limite", type=int, default=15)
    q.set_defaults(func=cmd_pendencias)

    c = sub.add_parser("corrigir", help="registra uma correção humana")
    c.add_argument("registro_id")
    c.add_argument("--campo", action="append", required=True)
    c.add_argument("--valor", action="append", required=True)
    c.add_argument("--motivo", required=True,
                   help="POR QUÊ — obrigatório, é o produto da curadoria")
    c.add_argument("--autor", default="mario")
    c.set_defaults(func=cmd_corrigir)

    a = sub.add_parser("ativas", help="lista as correções em vigor")
    a.add_argument("registro_id", nargs="?")
    a.set_defaults(func=cmd_ativas)

    r = sub.add_parser("revogar", help="desativa uma correção (não apaga)")
    r.add_argument("numero", type=int)
    r.set_defaults(func=cmd_revogar)

    l = sub.add_parser("local", help="cadastra/atualiza um local canônico")
    l.add_argument("nome")
    l.add_argument("--alias", action="append")
    l.add_argument("--fora-df", action="store_true")
    l.add_argument("--autor", default="mario")
    l.set_defaults(func=cmd_local)

    args = p.parse_args()
    con = conexao.conectar()
    try:
        args.func(con, args)
    finally:
        con.close()


if __name__ == "__main__":
    main()
