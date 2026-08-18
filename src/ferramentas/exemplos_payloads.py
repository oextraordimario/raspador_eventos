"""Regrava `docs/exemplos_payloads/` — um exemplar do que cada fonte respondeu.

    python src/ferramentas/exemplos_payloads.py       # lê a base de EVENTOS_DB_URL

Fora do pipeline. Existe para cavucar payload sem abrir a base: o que a fonte
manda, no formato dela, com todos os campos que a derivação hoje ignora — que é
onde nasce toda derivação nova.

**POR QUE LER DO `cru`, E NÃO RASPAR DE NOVO.** O `cru` É o que a fonte
respondeu: `gravar.bruto` não transforma nada, só carimba (o `hash` sai da
forma canônica, mas o `payload` gravado é fiel). Raspar outra vez faria uma
segunda chamada à fonte só para gerar documentação — e no Shotgun exigiria
subir o Chromium. A exceção honesta é uma: a **listagem V2 do Ticket and Go**
nunca chega ao `cru` (o `ERAS` registra que o payload guardado como `catalogo`
já é o detalhe da rota antiga), então esse payload não tem exemplar aqui.

**O MASCARAMENTO É POR PADRÃO DO VALOR, NÃO POR LISTA DE CAMPOS.** O saneamento
de 11/07/2026 foi feito à mão, campo a campo, no dia de abrir o repo — e numa
pasta que se regenera isso não sobrevive: fonte que passasse a mandar o
telefone do produtor num campo novo o publicaria, e ninguém seria avisado. É a
mesma lição que o `before_send` do PostHog pagou com o `$session_entry_url`.
Aqui toda string do JSON é varrida por PADRÃO (e-mail, telefone, CPF, JWT); o
nome da chave é só reforço, nunca a rede principal.

Quanto foi mascarado sai contado na saída do comando — número que despenca de
uma rodada para outra é sinal de que a fonte mudou de forma, não de que o dado
sumiu.
"""

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from base import conexao                                          # noqa: E402
from coleta import gravar                                         # noqa: E402

DESTINO = RAIZ / "docs" / "exemplos_payloads"

TABELA_INICIO = "<!-- TABELA GERADA - nao editar a mao -->"
TABELA_FIM = "<!-- FIM DA TABELA GERADA -->"

# --- mascaramento ---------------------------------------------------------

_PADROES = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "contato-mascarado@example.com"),
    (re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}"), "000.000.000-00"),
    # Telefone brasileiro. Três exigências, e cada uma pagou por si: separador
    # só ESPAÇO ou HÍFEN (com o ponto, a regra comia o timestamp decimal do
    # nome do pôster da Ingresse — `1768252345.1234403.jpg` virava telefone) e
    # bordas sem dígito (senão casa no meio de qualquer id longo).
    (re.compile(r"(?<!\d)(?:\+55[\s-]?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]\d{4}(?!\d)"),
     "(61) 90000-0000"),
    # JWT e afins: três blocos base64 separados por ponto.
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}"), "jwt.mascarado.aqui"),
]

# Reforço por nome de chave, para o segredo que não tem forma reconhecível — o
# `authToken` do pixel do Facebook é só um número. Nunca é a rede principal.
_CHAVES = re.compile(r"token|secret|senha|password|api_?key|authorization",
                     re.IGNORECASE)


def mascarar(valor, chave=None, contador=None):
    contador = {} if contador is None else contador
    if isinstance(valor, dict):
        return {k: mascarar(v, k, contador) for k, v in valor.items()}
    if isinstance(valor, list):
        return [mascarar(v, chave, contador) for v in valor]
    if not isinstance(valor, str):
        # Um `authToken` numérico continua sendo segredo. Só se zera quando a
        # chave denuncia — número não tem padrão que o distinga de um id.
        if chave and _CHAVES.search(chave) and isinstance(valor, (int, float)):
            contador["chave"] = contador.get("chave", 0) + 1
            return 0
        return valor
    novo = valor
    for padrao, troca in _PADROES:
        novo, n = padrao.subn(troca, novo)
        if n:
            contador["padrao"] = contador.get("padrao", 0) + n
    if chave and _CHAVES.search(chave) and novo and novo == valor:
        contador["chave"] = contador.get("chave", 0) + 1
        novo = "mascarado"
    return novo


# --- seleção do exemplar --------------------------------------------------

def _exemplares(con):
    """nome do arquivo -> o exemplar e sua procedência."""
    saida = {}
    for fonte in gravar.FONTES:
        # O id com MAIS origens, e o mais recente entre os empatados: o valor
        # didático está em seguir o MESMO evento do catálogo até o lote.
        linha = con.execute(
            f"SELECT id_nativo FROM cru.{fonte} GROUP BY id_nativo "
            f"ORDER BY count(DISTINCT origem) DESC, max(raspado_em) DESC "
            f"LIMIT 1").fetchone()
        if not linha:
            continue
        for r in con.execute(
                f"SELECT DISTINCT ON (origem) origem, payload, api, raspado_em "
                f"FROM cru.{fonte} WHERE id_nativo = %s "
                f"ORDER BY origem, raspado_em DESC",
                (linha["id_nativo"],)).fetchall():
            saida[f"{fonte}_{r['origem']}"] = {
                "payload": r["payload"], "api": r["api"],
                "raspado_em": r["raspado_em"],
                "chave": f"`{fonte}:{linha['id_nativo']}`"}

    r = con.execute("SELECT cinema_id, dia, payload, raspado_em FROM cru.cinema "
                    "ORDER BY raspado_em DESC, dia LIMIT 1").fetchone()
    if r:
        saida["cinema_grade"] = {
            "payload": r["payload"], "api": "ingresso.com/sessions",
            "raspado_em": r["raspado_em"],
            "chave": f"cinema `{r['cinema_id']}`, dia {r['dia']}"}

    # Instagram: o post e a extração DO MESMO shortcode — é o par que ensina (o
    # que a visão leu, ao lado do que ela recebeu). Story fica de fora: tem a
    # mesma forma do post e duplicaria dado de terceiro num repo público.
    r = con.execute(
        "SELECT code FROM cru.instagram WHERE origem IN ('post','extracao') "
        "GROUP BY code HAVING count(DISTINCT origem) = 2 "
        "ORDER BY max(raspado_em) DESC LIMIT 1").fetchone()
    if r:
        for x in con.execute(
                "SELECT perfil, origem, payload, raspado_em FROM cru.instagram "
                "WHERE code = %s AND origem IN ('post','extracao')",
                (r["code"],)).fetchall():
            saida[f"instagram_{x['origem']}"] = {
                "payload": x["payload"], "api": "monid/tikhub",
                "raspado_em": x["raspado_em"],
                "chave": f"@{x['perfil']}, post `{r['code']}`"}

    r = con.execute("SELECT filme_id, payload, raspado_em FROM cru.tmdb "
                    "ORDER BY length(payload) DESC LIMIT 1").fetchone()
    if r:
        saida["tmdb_busca"] = {"payload": r["payload"], "api": "tmdb/search",
                               "raspado_em": r["raspado_em"],
                               "chave": f"filme `{r['filme_id']}`"}
    return saida


def main():
    con = conexao.conectar()
    try:
        exemplares = _exemplares(con)
    finally:
        con.close()

    linhas = ["| arquivo | exemplar | origem | `api` (era do endpoint) | coletado |",
              "|---|---|---|---|---|"]
    total = 0
    for nome, dado in exemplares.items():
        contador = {}
        payload = mascarar(json.loads(dado["payload"]), contador=contador)
        texto = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        (DESTINO / f"{nome}.json").write_text(texto, encoding="utf-8")
        total += len(texto)
        print(f"{nome + '.json':28} {len(texto) // 1024:4} KB   "
              f"{sum(contador.values())} mascarado(s)   {dado['chave']}")
        linhas.append(
            f"| `{nome}.json` | {dado['chave']} | `{nome.split('_', 1)[1]}` | "
            f"`{dado['api'] or '—'}` | {(dado['raspado_em'] or '')[:10]} |")

    readme = DESTINO / "README.md"
    texto = readme.read_text(encoding="utf-8")
    antes, _, resto = texto.partition(TABELA_INICIO)
    _, _, depois = resto.partition(TABELA_FIM)
    readme.write_text(f"{antes}{TABELA_INICIO}\n\n" + "\n".join(linhas)
                      + f"\n\n{TABELA_FIM}{depois}", encoding="utf-8")
    print(f"\n{len(exemplares)} arquivos, {total // 1024} KB no total.")


if __name__ == "__main__":
    main()
