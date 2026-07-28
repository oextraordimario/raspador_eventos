import Link from 'next/link'
import { MARCA } from '../../lib/config'
import Enviado from './Enviado'

export const metadata = {
  title: 'falar com a gente',
  description: `Reportar um erro, sugerir algo ou pedir a sua casa no ${MARCA.nome}.`,
  // formulário não tem o que indexar, e a versão ?ok=1 seria conteúdo duplicado
  robots: { index: false, follow: true },
}

// Rota própria, e não uma seção do /sobre, por uma razão mecânica: o POST
// responde 303 e precisa de um endereço para onde mandar a pessoa de volta.
// É o que mantém o canal funcionando sem JS — nada aqui depende de fetch.
export const dynamic = 'force-dynamic'

const TIPOS = [
  { valor: 'bug', rotulo: 'achei um erro' },
  { valor: 'casa', rotulo: 'quero minha casa aqui' },
  { valor: 'sugestao', rotulo: 'tenho uma sugestão' },
  { valor: 'outro', rotulo: 'outro assunto' },
]

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

            {/* <form> NATIVO, sem fetch: é o único jeito de o canal funcionar
                sem JS, como o resto do site. Quem responde é a função Python
                (api/dados.py), que redireciona de volta para cá. */}
            <form className="form" method="post" action="/api/dados/feedback">
              <label className="campo">
                <span className="campo-nome">assunto</span>
                <select name="tipo" defaultValue="bug" required>
                  {TIPOS.map((t) => (
                    <option key={t.valor} value={t.valor}>{t.rotulo}</option>
                  ))}
                </select>
              </label>

              <label className="campo">
                <span className="campo-nome">o que aconteceu</span>
                <textarea name="mensagem" rows={6} maxLength={2000} required
                          placeholder="Conte com as suas palavras. Se for sobre um evento específico, cola o link dele aqui." />
              </label>

              <label className="campo">
                <span className="campo-nome">
                  contato <em>(opcional)</em>
                </span>
                <input name="contato" type="text" maxLength={200}
                       placeholder="e-mail ou @ do Instagram" />
                <small>
                  Só serve para a gente responder sobre isto. Fica numa base
                  privada e sai se você pedir — veja o{' '}
                  <Link href="/sobre">sobre</Link>.
                </small>
              </label>

              {/* honeypot: pessoa nenhuma vê este campo (o CSS o tira da tela).
                  Preenchido = robô, e a resposta é de sucesso, sem gravar. */}
              <div className="isca" aria-hidden="true">
                <label>
                  não preencha este campo
                  <input name="site" type="text" tabIndex={-1} autoComplete="off" />
                </label>
              </div>

              <input type="hidden" name="pagina" value={de} />
              <button className="cta" type="submit">enviar</button>
            </form>
          </>
        )}
      </article>

      {/* só instrumenta; não interfere no envio (que é do navegador) */}
      <Enviado ok={ok} tipo={sp?.tipo} />
    </>
  )
}
