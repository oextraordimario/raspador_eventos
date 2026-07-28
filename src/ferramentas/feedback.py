"""CLI de leitura do canal de feedback (NI-52) — a outra metade do botão.

Sem isto o botão seria decorativo: a tabela encheria e ninguém leria. O
relatório da rodada avisa QUE chegou coisa nova (`atualizar.py`); esta
ferramenta é o que mostra O QUE chegou.

Uso (da raiz do repo):
    python src/ferramentas/feedback.py listar [--todos] [--limite 50]
    python src/ferramentas/feedback.py lido <id>

Não existe `apagar`, e é decisão: o dado é curto, e apagar linha de dado de
pessoa por linha de comando é o tipo de ação destrutiva que não precisa
existir. Se alguém pedir remoção, o pedido é raro o bastante para passar por
uma sessão consciente no banco.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from servico import feedback  # noqa: E402

_ROTULO = {"bug": "ERRO", "casa": "CASA", "sugestao": "SUGESTÃO",
           "outro": "OUTRO"}


def cmd_listar(args):
    itens = feedback.listar(todos=args.todos, limite=args.limite)
    if not itens:
        print("Nada não lido." if not args.todos else "Nada por aqui.")
        return
    for f in itens:
        marca = "" if f["lido"] else "  ← não lido"
        print(f"\n=== #{f['id']}  [{_ROTULO.get(f['tipo'], f['tipo'])}]  "
              f"{f['em'][:16].replace('T', ' ')}{marca}")
        if f["pagina"]:
            print(f"    de: {f['pagina']}")
        if f["contato"]:
            print(f"    contato: {f['contato']}")
        for linha in f["mensagem"].splitlines():
            print(f"    {linha}")
    print(f"\n{len(itens)} registro(s). Marque como lido com: "
          f"python src/ferramentas/feedback.py lido <id>")


def cmd_lido(args):
    n = feedback.marcar_lido(args.id)
    print(f"#{args.id} marcado como lido." if n else f"#{args.id} não existe.")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("listar", help="o que as pessoas escreveram")
    l.add_argument("--todos", action="store_true",
                   help="inclui os já lidos (default: só os não lidos)")
    l.add_argument("--limite", type=int, default=50)
    l.set_defaults(func=cmd_listar)

    m = sub.add_parser("lido", help="marca um registro como lido")
    m.add_argument("id", type=int)
    m.set_defaults(func=cmd_lido)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
