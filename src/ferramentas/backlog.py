"""CRUD do backlog (`docs/backlogs/nao-iniciado.yaml` e `rejeitado.yaml`) sem
reescrever o arquivo inteiro a cada item novo.

Uso (da raiz do repo):
    python src/ferramentas/backlog.py listar [--arquivo nao-iniciado|rejeitado|todos]
        [--status S] [--prioridade P] [--eixo E] [--fase F] [--busca TEXTO]
    python src/ferramentas/backlog.py ver <codigo>
    python src/ferramentas/backlog.py add --arquivo nao-iniciado|rejeitado --de <item.yaml>

`add` lê um dict (YAML ou JSON) de um arquivo com os campos do item — SEM
`codigo` (é atribuído automaticamente como o próximo NI-##/RJ-## livre, nunca
reaproveitado) — e ANEXA ao arquivo, formatado no estilo já usado (bloco
`- codigo: ...`, `detalhe: |` com a prosa indentada). Nunca reserializa o
arquivo inteiro via yaml.dump: isso destruiria os comentários de cabeçalho e
o estilo dos itens já escritos (aspas, listas em uma linha, blocos `|`).

Campos de `nao-iniciado`: status, prioridade, rank (auto se omitido: 0=critica
1=alta 2=media 3=baixa), esforco, eixo, fase, titulo, resumo, detalhe
(obrigatórios) + data (default: hoje), depende_de/relacionado (default: []),
caso_real (opcional, string ou lista de strings).

Campos de `rejeitado`: iguais, MENOS status/prioridade/rank/esforco (não se
prioriza o que foi descartado).

Exemplo de `item.yaml` para `add`:
    eixo: raspagem
    fase: 1
    titulo: "Título curto"
    resumo: "uma frase — o que é e por que importa"
    prioridade: alta
    esforco: M
    detalhe: |
      Prosa livre, várias linhas, à vontade.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVOS = {
    "nao-iniciado": RAIZ / "docs/backlogs/nao-iniciado.yaml",
    "rejeitado": RAIZ / "docs/backlogs/rejeitado.yaml",
}
PREFIXO = {"nao-iniciado": "NI", "rejeitado": "RJ"}
RANK_POR_PRIORIDADE = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}

# Ordem canônica dos campos no arquivo (a mesma dos itens já escritos).
CAMPOS = {
    "nao-iniciado": ["codigo", "status", "prioridade", "rank", "esforco", "eixo",
                     "fase", "titulo", "resumo", "data", "depende_de",
                     "relacionado", "caso_real", "detalhe"],
    "rejeitado": ["codigo", "eixo", "fase", "titulo", "resumo", "data",
                  "depende_de", "relacionado", "caso_real", "detalhe"],
}
OBRIGATORIOS = {
    "nao-iniciado": ["status", "prioridade", "eixo", "fase", "titulo", "resumo", "detalhe"],
    "rejeitado": ["eixo", "fase", "titulo", "resumo", "detalhe"],
}


def carregar(arquivo):
    texto = ARQUIVOS[arquivo].read_text(encoding="utf-8")
    return yaml.safe_load(texto) or []


def proximo_codigo(arquivo):
    # NI-## pode morar em QUALQUER um dos dois arquivos (item rejeitado
    # mantém o código de origem) — por isso varre os dois, sempre.
    prefixo = PREFIXO[arquivo]
    maior = 0
    for outro in ARQUIVOS:
        for item in carregar(outro):
            m = re.match(rf"{prefixo}-(\d+)$", str(item.get("codigo", "")))
            if m:
                maior = max(maior, int(m.group(1)))
    return f"{prefixo}-{maior + 1}"


def _yaml_str(valor):
    return json.dumps(valor, ensure_ascii=False)


def _yaml_lista_codigos(valores):
    return "[" + ", ".join(str(v) for v in (valores or [])) + "]"


def _yaml_caso_real(valor):
    if isinstance(valor, list):
        return "[" + ", ".join(_yaml_str(v) for v in valor) + "]"
    return _yaml_str(valor)


def _formatar_detalhe(texto):
    linhas = texto.rstrip("\n").split("\n")
    corpo = "\n".join(("    " + l if l else "") for l in linhas)
    return "  detalhe: |\n" + corpo + "\n"


def formatar_item(item, arquivo):
    campos = CAMPOS[arquivo]
    partes = [f'- codigo: {item["codigo"]}']
    for campo in campos:
        if campo in ("codigo", "detalhe") or campo not in item:
            continue
        valor = item[campo]
        if campo in ("depende_de", "relacionado"):
            partes.append(f"  {campo}: {_yaml_lista_codigos(valor)}")
        elif campo == "caso_real":
            partes.append(f"  caso_real: {_yaml_caso_real(valor)}")
        elif campo in ("titulo", "resumo"):
            partes.append(f"  {campo}: {_yaml_str(valor)}")
        else:
            partes.append(f"  {campo}: {valor}")
    return "\n".join(partes) + "\n" + _formatar_detalhe(item["detalhe"])


def validar(item, arquivo):
    faltando = [c for c in OBRIGATORIOS[arquivo] if not item.get(c)]
    if faltando:
        sys.exit(f"Faltam campos obrigatórios pra {arquivo}: {', '.join(faltando)}")
    if arquivo == "nao-iniciado":
        if item["status"] not in ("pendente", "nao-iniciado", "em-andamento"):
            sys.exit(f"status inválido: {item['status']!r}")
        if item["prioridade"] not in RANK_POR_PRIORIDADE:
            sys.exit(f"prioridade inválida: {item['prioridade']!r}")
        item.setdefault("rank", RANK_POR_PRIORIDADE[item["prioridade"]])
        if not item.get("esforco"):
            sys.exit("falta esforco (P|M|G)")


def cmd_add(args):
    arquivo = args.arquivo
    bruto = Path(args.de).read_text(encoding="utf-8")
    item = yaml.safe_load(bruto) if not bruto.lstrip().startswith("{") else json.loads(bruto)
    if not isinstance(item, dict):
        sys.exit("--de precisa apontar pra um dict YAML ou JSON com os campos do item")
    if "codigo" in item:
        sys.exit("não passe 'codigo' — é atribuído automaticamente")

    validar(item, arquivo)
    item.setdefault("data", date.today().isoformat())
    item.setdefault("depende_de", [])
    item.setdefault("relacionado", [])
    item["codigo"] = proximo_codigo(arquivo)

    caminho = ARQUIVOS[arquivo]
    texto_atual = caminho.read_text(encoding="utf-8")
    separador = "" if texto_atual.endswith("\n\n") else ("\n" if texto_atual.endswith("\n") else "\n\n")
    caminho.write_text(texto_atual + separador + formatar_item(item, arquivo), encoding="utf-8")

    print(f"{item['codigo']} adicionado em {caminho.relative_to(RAIZ)}")


def cmd_listar(args):
    alvos = ["nao-iniciado", "rejeitado"] if args.arquivo == "todos" else [args.arquivo]
    total = 0
    for arquivo in alvos:
        for item in carregar(arquivo):
            if args.status and item.get("status") != args.status:
                continue
            if args.prioridade and item.get("prioridade") != args.prioridade:
                continue
            if args.eixo and item.get("eixo") != args.eixo:
                continue
            if args.fase and str(item.get("fase")) != args.fase:
                continue
            if args.busca:
                alvo = f"{item.get('titulo', '')} {item.get('resumo', '')}".lower()
                if args.busca.lower() not in alvo:
                    continue
            total += 1
            extra = " ".join(
                f"{k}={item[k]}" for k in ("status", "prioridade", "eixo") if item.get(k)
            )
            print(f"{item['codigo']:<7} {extra:<38} {item.get('titulo', '')}")
    print(f"\n{total} item(ns).")


def cmd_ver(args):
    for arquivo in ARQUIVOS:
        for item in carregar(arquivo):
            if item.get("codigo") == args.codigo:
                print(f"# {arquivo}\n")
                print(formatar_item(item, arquivo))
                return
    sys.exit(f"{args.codigo} não encontrado")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("listar", help="lista itens, com filtros")
    l.add_argument("--arquivo", choices=[*ARQUIVOS, "todos"], default="nao-iniciado")
    l.add_argument("--status")
    l.add_argument("--prioridade")
    l.add_argument("--eixo")
    l.add_argument("--fase")
    l.add_argument("--busca")
    l.set_defaults(func=cmd_listar)

    v = sub.add_parser("ver", help="mostra um item inteiro pelo código")
    v.add_argument("codigo")
    v.set_defaults(func=cmd_ver)

    a = sub.add_parser("add", help="adiciona item novo (código automático)")
    a.add_argument("--arquivo", choices=[*ARQUIVOS], required=True)
    a.add_argument("--de", required=True, help="arquivo YAML/JSON com os campos (sem codigo)")
    a.set_defaults(func=cmd_add)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
