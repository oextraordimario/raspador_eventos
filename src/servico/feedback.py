"""Canal de feedback do site público (NI-52, spec 20260728_rework-site §7).

É a PRIMEIRA escrita que o site faz na base — até aqui as duas portas (site e
MCP) só liam. Por isso ela mora aqui e não na `api/dados.py`: a API traduz o
formulário e mais nada, como já traduz querystring para a `consulta.py`. Toda
a regra (o que é um envio válido, o que é abuso, o que vira linha) está neste
módulo, num lugar só.

A guarda contra abuso não guarda NADA sobre quem enviou (ver sql/uso/feedback.sql):
não há IP nem user-agent, e o teto por janela é GLOBAL. O custo aceito é que uma
enxurrada bloqueia envios legítimos por um minuto; o ganho é não manter dado
pessoal extra nem estado de rate limit. Se o abuso se provar real, a resposta
certa é BotID/WAF na borda da Vercel, não uma tabela de IPs aqui.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1])
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from base import conexao  # noqa: E402

# Lista FECHADA: o corpo de um POST é entrada de estranho, igual à querystring.
# A ordem é a que aparece no formulário.
TIPOS = ("bug", "sugestao", "casa", "outro")

# Tetos de tamanho. Corta em vez de rejeitar: quem escreveu demais teve o
# trabalho de escrever, e devolver erro perderia o texto inteiro.
MSG_MAX = 2000
CONTATO_MAX = 200
PAGINA_MAX = 300

# Teto por janela, global (ver docstring).
JANELA_S = 60
TETO_JANELA = 10


def _agora():
    return datetime.now(timezone.utc).isoformat()


def _curto(v, teto):
    """Texto opcional: espaços fora, vazio vira NULL, e nunca passa do teto."""
    v = (v or "").strip()
    return v[:teto] if v else None


def registrar(tipo, mensagem, contato=None, pagina=None, isca=None, con=None):
    """Grava um envio do formulário. Devolve {"ok": True} ou {"erro": <slug>}.

    `isca` é o honeypot: um campo escondido por CSS que pessoa nenhuma vê. Se
    veio preenchido, é robô — e a resposta é de SUCESSO, sem gravar nada. Dizer
    "recusado" ensinaria o robô a tentar de novo sem o campo.

    Slugs de erro (a API os traduz em status): `tipo` (fora da lista),
    `vazio` (sem mensagem), `muitos` (teto por janela).
    """
    if isca:
        return {"ok": True}
    if tipo not in TIPOS:
        return {"erro": "tipo"}
    mensagem = (mensagem or "").strip()
    if not mensagem:
        return {"erro": "vazio"}

    proprio = con is None
    con = con or conexao.conectar()
    try:
        limite = (datetime.now(timezone.utc)
                  - timedelta(seconds=JANELA_S)).isoformat()
        recentes = con.execute(
            "SELECT count(*) AS n FROM uso.feedback WHERE em > %s",
            (limite,)).fetchone()["n"]
        if recentes >= TETO_JANELA:
            return {"erro": "muitos"}

        con.execute(
            "INSERT INTO uso.feedback (em, tipo, mensagem, contato, pagina) "
            "VALUES (%s, %s, %s, %s, %s)",
            (_agora(), tipo, mensagem[:MSG_MAX],
             _curto(contato, CONTATO_MAX), _curto(pagina, PAGINA_MAX)))
        con.commit()
        return {"ok": True}
    finally:
        if proprio:
            con.close()


def nao_lidos(con=None):
    """Quantos envios ainda não foram lidos — o número que o relatório da
    rodada mostra. Sem isto o botão seria decorativo: a tabela encheria e
    ninguém saberia."""
    proprio = con is None
    con = con or conexao.conectar()
    try:
        return con.execute(
            "SELECT count(*) AS n FROM uso.feedback WHERE lido = 0"
        ).fetchone()["n"]
    finally:
        if proprio:
            con.close()


def listar(todos=False, limite=50, con=None):
    """Envios, do mais novo para o mais velho. Por padrão só os não lidos."""
    proprio = con is None
    con = con or conexao.conectar()
    try:
        onde = "" if todos else "WHERE lido = 0"
        return [dict(r) for r in con.execute(
            f"SELECT id, em, tipo, mensagem, contato, pagina, lido "
            f"FROM uso.feedback {onde} ORDER BY em DESC LIMIT %s", (limite,))]
    finally:
        if proprio:
            con.close()


def marcar_lido(id_, con=None):
    """Marca UM envio como lido. Não existe `apagar`: o dado é curto, e apagar
    linha de dado de pessoa por CLI é comando destrutivo que não precisa
    existir."""
    proprio = con is None
    con = con or conexao.conectar()
    try:
        n = con.execute("UPDATE uso.feedback SET lido = 1 WHERE id = %s",
                        (id_,)).rowcount
        con.commit()
        return n
    finally:
        if proprio:
            con.close()
