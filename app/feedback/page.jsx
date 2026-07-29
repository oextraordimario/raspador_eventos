import Link from 'next/link'
import { MARCA } from '../../lib/config'
import Enviado from './Enviado'
import FormularioFeedback from '../FormularioFeedback'

export const metadata = {
  title: 'falar com a gente',
  description: `Reportar um erro, sugerir algo ou pedir a sua casa no ${MARCA.nome}.`,
  // formulário não tem o que indexar, e a versão ?ok=1 seria conteúdo duplicado
  robots: { index: false, follow: true },
}

// Rota própria, e não uma seção do /sobre, por uma razão mecânica: o POST
// responde 303 e precisa de um endereço para onde mandar a pessoa de volta.
// É o que mantém o canal funcionando sem JS — nada aqui depende de fetch.
// Também é o destino do fallback do ModalFeedback (FAB), quando o clique
// não é interceptado por JS.
export const dynamic = 'force-dynamic'

const ERROS = {
  vazio: 'Faltou escrever a mensagem.',
  tipo: 'Escolha um dos assuntos da lista.',
  muitos: 'Chegou muita coisa ao mesmo tempo agora. Tente de novo em um minuto.',
  interno: 'Deu erro do nosso lado. Se puder, tente de novo daqui a pouco.',
}

export default async function Feedback({ searchParams }) {
  const sp = await searchParams
  const ok = sp?.ok === '1'
  const erro = sp?.erro ? (ERROS[sp.erro] ?? ERROS.interno) : null
  const de = sp?.de ?? ''

  return (
    <>
      <Link className="voltar" href="/">← voltar</Link>

      <article className="doc">
        <h1>falar com a gente</h1>

        {ok ? (
          <>
            <div className="note">
              <strong>Recebido.</strong> Obrigado — isso vira trabalho de
              verdade por aqui. Se você deixou contato, a gente responde.
            </div>
            <p>
              <Link className="cta ghost" href="/feedback">enviar outro</Link>
            </p>
          </>
        ) : (
          <>
            <p>
              O {MARCA.nome} é feito por uma pessoa só e depende de gente
              contando o que está errado. Preço desatualizado, evento que não
              existe, casa faltando, ideia de melhoria — manda.
            </p>

            {erro && <div className="note erro">{erro}</div>}

            <FormularioFeedback pagina={de} />
          </>
        )}
      </article>

      {/* só instrumenta; não interfere no envio (que é do navegador) */}
      <Enviado ok={ok} tipo={sp?.tipo} />
    </>
  )
}
