"""Atualização sob demanda da base de eventos — o comando único da Fase 0.

DOIS TEMPOS, e a fronteira entre eles é o desenho inteiro (spec
20260728_arquitetura-medalhao §8): **tudo que tem rede é coleta, tudo que é a
seco é tratamento, e só o tratamento escreve em `tratado`**.

  1. COLETA — raspa as 5 fontes (tolerante a falha por fonte) → grava o payload
     em `cru.<fonte>` e o registro da coleta em `operacao.coletas` → descrever
     (payload de detalhe dos que ainda não têm) → precificar (payload de tickets
     dos futuros na janela de 30 dias; não é incremental, preço é volátil) →
     cinema (grade dos 8 cinemas) → instagram (posts/stories + extração do flyer
     por visão) → flyer no storage próprio.
  2. TRATAMENTO — `tratamento/ciclo.py`, numa transação só: reconstrói
     `tratado` inteira a partir do cru, deriva `sumido` de `operacao.coletas`,
     enriquece (ruído + dedupe cross-fonte), reaplica a curadoria humana e
     reconstrói o FTS.

Depois: TMDB e cópia de pôster (que só sabem o que buscar depois de a grade
existir, então rodam entre um ciclo e outro), poda do histórico do cru,
relatório de saúde (com comparação vs. rodada anterior) e o registro da rodada
em `operacao.execucoes` (NI-19).

**Este arquivo é o CLI, não os passos.** Cada passo mora em `pipeline/passos.py`
e é chamável por qualquer orquestrador — aqui ficam só a leitura de `sys.argv`,
a ordem em que os passos são chamados e o que fazer quando um falha (spec
20260814_orquestracao-dagster §5.2). O Dagster chama os mesmos passos, na mesma
posição, sem duplicar uma linha de lógica.

Uso (da raiz do repo):
    python src/pipeline/atualizar.py                    # pipeline completo
    python src/pipeline/atualizar.py --sem-shotgun      # pula o Shotgun (lento, usa navegador)
    python src/pipeline/atualizar.py --sem-cinema       # pula a grade de cinema
    python src/pipeline/atualizar.py --sem-tmdb         # pula o enriquecimento TMDB dos filmes
    python src/pipeline/atualizar.py --sem-instagram    # pula o Instagram (Monid/claude -p)
    python src/pipeline/atualizar.py --precificar-tudo  # tickets de TODOS os futuros (ex.: 1ª carga)
    python src/pipeline/atualizar.py --so-derivar       # não raspa; reconstrói `tratado` do cru
    python src/pipeline/atualizar.py --so-enriquecer    # não raspa; só reaplica regras + FTS
"""

import sys
import time
from datetime import datetime, timezone

from pathlib import Path

# Entrypoint: põe src/ no sys.path para os pacotes de estágio resolverem
# (namespace packages, sem __init__.py). Rodar da raiz do repo:
#     python src/pipeline/atualizar.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from base import conexao                                          # noqa: E402
from coleta import gravar                                         # noqa: E402
from pipeline import execucoes, passos                            # noqa: E402
from tratamento import ciclo, curadoria                           # noqa: E402


def _raspar(incluir_shotgun=True, apenas=None, locais_df=None):
    """As cinco plataformas, uma de cada vez: uma fonte quebrada não esconde as
    outras (quem trata a exceção é o `passos.coletar`, que devolve o erro em vez
    de levantar).

    `apenas` restringe a nomes de fonte — é como a rodada local pega só o
    Shotgun, que não funciona no CI (ver `--rodada-local` no main).
    """
    nomes = [n for n in passos.ORDEM_FONTES
             if incluir_shotgun or n != "shotgun"]
    if apenas:
        nomes = [n for n in nomes if n in apenas]
    return {n: passos.coletar(n, locais_df=locais_df) for n in nomes}


def _instagram(erros, extrair=True):
    """A fonte Instagram inteira, do ponto de vista do CLI: coleta + (quando é
    uma rodada que pode) a extração do flyer.

    `extrair=False` (flag --sem-extracao-flyer) faz a coleta parar na Bronze:
    raspa os perfis, grava os posts e NÃO chama a visão. É o modo do cron (spec
    20260726_abrir-ao-publico §3 passo 2, "caminho 1"): o `claude -p` roda na
    ASSINATURA e não há login de assinatura em CI. A fila é incremental e
    re-tentável por desenho, então o que ficou pendente é extraído na próxima
    rodada LOCAL — o resultado reporta quantos são, para o pendente não virar
    invisível.
    """
    resultado = passos.coletar_instagram(erros)
    if resultado is None or "erro" in resultado:
        return resultado
    if not extrair:
        # Caminho 1: a Bronze está atualizada, a visão fica para a rodada
        # local. Não é erro nem falha — é escopo do cron.
        pendentes = passos.pendentes_extracao()
        print(f"[instagram] extração do flyer PULADA (--sem-extracao-flyer): "
              f"{pendentes} posts aguardando a próxima rodada local.")
        resultado.update(extraidos=None, falhas_extracao=None,
                         pendentes_extracao=pendentes)
        return resultado
    resultado.update(passos.extrair_flyers(erros))
    return resultado


def main():
    inicio = time.monotonic()
    iniciada_em = datetime.now(timezone.utc).isoformat()
    so_enriquecer = "--so-enriquecer" in sys.argv
    so_derivar = "--so-derivar" in sys.argv
    # --rodada-local: o que o CI NÃO consegue fazer. Nasceu como
    # --so-instagram (a extração de flyer exige a assinatura do Claude) e em
    # 2026-07-28 ganhou o Shotgun, que o runner do Actions não consegue ler
    # (NI-58). O nome antigo continua valendo — está em doc, hábito e no aviso
    # que o próprio relatório do cron imprime.
    rodada_local = ("--rodada-local" in sys.argv or "--so-instagram" in sys.argv)
    sem_shotgun = "--sem-shotgun" in sys.argv
    sem_cinema = "--sem-cinema" in sys.argv
    sem_instagram = "--sem-instagram" in sys.argv
    sem_extracao = "--sem-extracao-flyer" in sys.argv
    modo = ("so-enriquecer" if so_enriquecer else "so-derivar" if so_derivar
            else "rodada-local" if rodada_local
            else "cron" if sem_extracao
            else "sem-shotgun" if sem_shotgun else "completo")

    # Conexões CURTAS por bloco (2026-07-27, a pedido do autor): o pipeline
    # intercala minutos de raspagem/visão com escrita na base, e conexão
    # parada é derrubada pela rede em silêncio (SSL closed no meio da rodada,
    # visto no Zig). Cada bloco abre a sua e fecha; os passos de raspagem
    # abrem as próprias depois da rede. Alongar a vida da conexão é cilada.
    # Único ponto do pipeline que aplica DDL (conectar() não aplica por padrão
    # desde 2026-07-28 — spec 20260728_arquitetura-medalhao, D9). As conexões
    # seguintes só leem e escrevem dado.
    con = conexao.conectar(aplicar_schema=True)
    passos.checar_schema(con)
    # A referência canônica de casas do DF, lida ANTES da raspagem: o filtro
    # `_do_df` do Ticket and Go depende dela, e o coletor não conhece a base.
    locais_df = curadoria.nomes_df(con)
    con.close()

    resultados, erros = {}, []
    desc = prec = None
    if not (so_enriquecer or so_derivar):
        # --rodada-local: rodada curta com o que só a máquina do autor faz.
        # (a) o Shotgun, que devolve 0 no runner do Actions e vai bem aqui
        #     (NI-58) — sem descrever/precificar, que ele não usa: o JSON-LD
        #     do catálogo já traz descrição, line-up e preço;
        # (b) a fila de extração de flyer deixada pelo cron (que roda com
        #     --sem-extracao-flyer, porque a visão exige a assinatura).
        # Re-raspa os perfis de propósito — a URL de mídia do CDN expira em
        # horas, então a Bronze precisa estar fresca para a visão baixar.
        if rodada_local:
            if not sem_shotgun:
                resultados = _raspar(apenas=["shotgun"])
        else:
            resultados = _raspar(incluir_shotgun=not sem_shotgun,
                                 locais_df=locais_df)
            if resultados and all("erro" in r for r in resultados.values()):
                sys.exit("Todas as fontes falharam — base não atualizada.")
            # descrever/precificar leem a fila do cru (não da prata, que ainda
            # não foi reconstruída nesta rodada) e escrevem no cru. Tocam a base
            # a cada evento — os gaps são curtos, uma conexão para o bloco basta.
            con = conexao.conectar()
            desc = passos.descrever(con, erros)
            prec = passos.precificar(con, erros,
                                     tudo="--precificar-tudo" in sys.argv)
            con.close()
            if not sem_cinema:
                resultados["cinema"] = passos.coletar_cinema(erros)
        if not sem_instagram:
            r_insta = _instagram(erros, extrair=not sem_extracao)
            if r_insta is not None:
                resultados["instagram"] = r_insta
            # O flyer sobe para o storage próprio ANTES do tratamento, porque é
            # a derivação que grava a URL em eventos.imagem. Lê cru+operacao,
            # escreve em operacao — nada de `tratado`.
            con = conexao.conectar()
            passos.subir_midias_instagram(con, erros)
            con.close()

    # daqui em diante é tratamento/relatório: conexão nova — a raspagem acima
    # pode ter levado muitos minutos.
    con = conexao.conectar()

    # O ciclo inteiro do tratamento, numa transação só: enquanto ele reconstrói
    # `tratado`, o site e o MCP seguem lendo `public` (§8.1).
    saida = ciclo.executar(con, so_enriquecer=so_enriquecer)

    # TMDB e cópia de pôster DEPOIS do tratamento: a lista do que está em cartaz
    # É a tabela `tratado.filmes`, então não há como montá-la antes. Os dois
    # escrevem em `cru.tmdb` e `operacao.midias`; se trouxeram algo, o ciclo roda
    # de novo para aplicar (é idempotente e custa segundos).
    if (not (so_enriquecer or so_derivar or rodada_local)
            and not sem_cinema and "--sem-tmdb" not in sys.argv):
        novos = passos.enriquecer_cinema(con, erros) or 0
        novos += passos.copiar_posters(con, erros) or 0
        if novos:
            saida = ciclo.executar(con, so_enriquecer=so_enriquecer)

    # Desempate de slug não é rotina: quando aparece, é sintoma (dedupe frouxo
    # ou teto de comprimento agressivo). Silêncio aqui esconderia um endereço
    # com `-2` no fim que ninguém pediu.
    desempates = saida["slugs"]["desempates"]
    if desempates:
        print(f"\n[slug] {len(desempates)} endereço(s) precisaram de desempate:")
        for d in desempates[:10]:
            print(f"  - {d['id']} -> /{d['slug']}")

    cur = saida["curadoria"]
    if cur["aplicadas"] or cur["orfas"]:
        print(f"\n[curadoria] {cur['aplicadas']} correções reaplicadas"
              + (f" | {cur['orfas']} órfãs (registro sumiu da prata — "
                 f"aparecem em curado.pendencias)" if cur["orfas"] else ""))
    # Única exceção ao "nada é apagado" no cru, e só de versão INTERMEDIÁRIA
    # antiga: a mais recente de cada chave nunca tem sibling mais nova, então
    # nunca casa a condição. Não roda em --so-enriquecer (não houve coleta).
    if not so_enriquecer:
        podados = gravar.podar_historico(con, passos.JANELA_HISTORICO_DIAS)
        if podados:
            print(f"\n[cru] histórico podado (> {passos.JANELA_HISTORICO_DIAS} "
                  "dias): " + ", ".join(f"{f}: {n}" for f, n in podados.items()))
    duracao = time.monotonic() - inicio
    derivado, enriq = saida["derivado"], saida["enriquecimento"]
    sumidos = saida["sumidos"]
    if derivado and derivado["rejeitados"]:
        # Payload que a guarda do §6.3 reprovou. Nunca é silêncio: o evento
        # simplesmente não estaria na base, e ninguém saberia por quê.
        erros.extend({"passo": "tratar", **r} for r in derivado["rejeitados"])
    # O relatório lê execucoes ANTES do registro: a comparação é com a rodada
    # anterior de verdade, não com esta.
    passos.relatorio(con, resultados, derivado, saida["cinema"],
                     saida["instagram"], enriq, sumidos, duracao)
    execucoes.registrar_execucao(
        con, iniciada_em, round(duracao, 1), modo, resultados,
        {"descrever": desc, "precificar": prec, "derivado": derivado,
         "cinema": saida["cinema"], "instagram": saida["instagram"],
         "ruido": len(enriq["ruido"]), "dedupe_grupos": len(enriq["grupos"]),
         "sumidos": len(sumidos) if sumidos is not None else None},
        erros)
    con.close()


if __name__ == "__main__":
    main()
