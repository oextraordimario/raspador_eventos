import Link from 'next/link'
import { listarFilmes } from '../../lib/api'
import { MARCA } from '../../lib/config'
import FilmCard from './FilmCard'

export const revalidate = 300

export const metadata = {
  title: 'cinema',
  description: `Filmes em cartaz nos cinemas de ${MARCA.cidade}.`,
}

export default async function Filmes({ searchParams }) {
  const sp = await searchParams
  const texto = sp?.texto ?? ''
  const filmes = await listarFilmes({ texto })

  return (
    <>
      <div className="filtros">
        <form className="search" action="/filmes">
          <input name="texto" type="search" defaultValue={texto}
                 placeholder="animação, terror, comédia..."
                 aria-label="Buscar filmes" />
        </form>
        <div className="chips" role="group" aria-label="Filtros">
          <Link className="chip" href="/" data-on="0">festas &amp; shows</Link>
          <Link className="chip" href="/filmes" data-on="1">cinema</Link>
        </div>
      </div>

      <p className="count">
        {filmes.length} {filmes.length === 1 ? 'filme em cartaz' : 'filmes em cartaz'}
      </p>

      {filmes.length === 0 ? (
        <div className="empty">
          <strong>Nada em cartaz</strong>
          <span>
            {texto ? `Nenhum filme casa com “${texto}”.` : 'A grade ainda não foi coletada.'}
          </span>
        </div>
      ) : (
        <div className="list">
          {filmes.map((f) => (
            <FilmCard key={f.id} filme={f} />
          ))}
        </div>
      )}
    </>
  )
}
