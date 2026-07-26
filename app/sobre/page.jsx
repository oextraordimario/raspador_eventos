import Link from 'next/link'
import { MARCA } from '../../lib/config'

export const metadata = {
  title: 'sobre',
  description: `O que é o ${MARCA.nome}, de onde vem o dado e como pedir remoção.`,
}

// Esta página é o que torna a postura de ToS verificável por quem chegar
// reclamando — decorre da opção "agregador com atribuição" (anexo tos.md da
// spec). Sem ela, a postura existe só no repositório.
export default function Sobre() {
  return (
    <>
      <Link className="voltar" href="/">&lt; voltar</Link>

      <article className="doc">
        <h1>sobre</h1>

        <p>
          Descobrir o que tem pra fazer hoje à noite em {MARCA.cidade} exige pingar
          de site em site. Cada plataforma tem sua busca, e nenhuma mostra o que
          está nas outras. O {MARCA.nome} junta tudo numa lista só.
        </p>

        <h2>de onde vem o dado</h2>
        <p>
          Dos catálogos públicos do Sympla, Ingresse, Shotgun, Zig e Ticket and Go,
          da grade de cinema da Ingresso.com, e do Instagram de casas que divulgam
          a agenda só por lá. A coleta roda uma vez por dia.
        </p>
        <p>
          O que a gente faz com isso: junta o mesmo evento publicado em várias
          plataformas numa entrada só, tira anúncio e curso que se disfarçam de
          festa, e esconde o que foi cancelado ou saiu do ar.
        </p>

        <h2>não vendemos ingresso</h2>
        <p>
          Nenhum. Cada evento leva pro link de quem está vendendo, e é lá que a
          compra acontece — a gente não intermedia, não cobra taxa e não fica com
          nada. O preço que aparece aqui é o que a plataforma publicou na última
          coleta e pode ter mudado desde então.
        </p>

        <h2>a descrição vem cortada</h2>
        <p>
          De propósito. O texto do evento é escrito por quem organiza, e ele
          pertence a quem escreveu — mostramos o suficiente pra você entender o
          estilo da noite e decidir se abre o link. O texto completo fica na
          página da fonte.
        </p>

        <h2>é uma casa ou plataforma?</h2>
        <p>
          Se você quer que um evento, um perfil ou uma casa saia daqui, é só pedir
          — a gente tira, sem discussão.{' '}
          <a className="cta ghost" style={{ marginTop: 10 }}
             href="https://github.com/oextraordimario/raspador_eventos/issues/new"
             target="_blank" rel="noopener">
            pedir remoção
          </a>
        </p>

        <h2>quer usar pelo seu assistente de IA?</h2>
        <p>
          O projeto também funciona como conector: o seu assistente consulta a
          base direto e responde em linguagem natural, tipo “quais festas de
          pagode tem esse fim de semana?”. O código e as instruções estão no{' '}
          <a href="https://github.com/oextraordimario/raspador_eventos"
             target="_blank" rel="noopener">repositório</a>.
        </p>
      </article>
    </>
  )
}
