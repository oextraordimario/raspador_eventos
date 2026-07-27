import Link from 'next/link'
import { redirect } from 'next/navigation'
import { listarEventos, listarFilmes } from '../lib/api'
import { MARCA } from '../lib/config'

export const revalidate = 300

export const metadata = {
  description: MARCA.descricao,
}

export default async function Home({ searchParams }) {
  const sp = await searchParams
  // A lista de eventos morava aqui (/?periodo=fds&texto=...) antes de virar
  // /festas. Link antigo compartilhado ou indexado chega com filtro na URL —
  // quem chega assim quer a lista, não o hall: reencaminha com tudo.
  if (sp?.periodo || sp?.texto || sp?.gratis) {
    const q = new URLSearchParams()
    for (const k of ['periodo', 'texto', 'gratis']) if (sp?.[k]) q.set(k, sp[k])
    redirect(`/festas?${q}`)
  }

  // O número vivo é o que diferencia o hall de uma landing decorativa: ele
  // diz que a base existe e está fresca. API fora do ar → lista vazia → o
  // stat some, e o portal continua funcionando (página incompleta > quebrada).
  const [eventos, filmes] = await Promise.all([
    listarEventos({ periodo: '7d', limite: 200 }),
    listarFilmes({}),
  ])

  return (
    <div className="hall">
      <div className="hall-head">
        <h2>O que rola em {MARCA.cidade}, num lugar só.</h2>
        <p>
          Festas, shows e cinema — coletados todo dia das plataformas de
          ingresso, da grade dos cinemas e do Instagram das casas.
        </p>
      </div>

      <nav className="portais" aria-label="Seções do site">
        <Link className="portal" href="/festas">
          <span className="portal-title">festas &amp; shows</span>
          <span className="portal-desc">
            A noite da cidade: baladas, shows e festas, com preço, line-up e
            link para o ingresso.
          </span>
          <span className="portal-foot">
            {eventos.length > 0 && (
              <span className="portal-stat">
                {eventos.length} {eventos.length === 1 ? 'evento' : 'eventos'} nos próximos 7 dias
              </span>
            )}
            <span className="portal-arrow" aria-hidden="true">→</span>
          </span>
        </Link>

        <Link className="portal" href="/filmes">
          <span className="portal-title">cinema</span>
          <span className="portal-desc">
            O que está em cartaz nos cinemas da cidade, com horários, salas e
            preço de cada sessão.
          </span>
          <span className="portal-foot">
            {filmes.length > 0 && (
              <span className="portal-stat">
                {filmes.length} {filmes.length === 1 ? 'filme em cartaz' : 'filmes em cartaz'}
              </span>
            )}
            <span className="portal-arrow" aria-hidden="true">→</span>
          </span>
        </Link>
      </nav>
    </div>
  )
}
