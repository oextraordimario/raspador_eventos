import Link from 'next/link'
import { listarFilmes } from '../../lib/api'
import { MARCA } from '../../lib/config'

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
          <strong>&gt; nada em cartaz</strong>
          <span>
            {texto ? `nenhum filme casa com “${texto}”.` : 'a grade ainda não foi coletada.'}
          </span>
        </div>
      ) : (
        <div className="list">
          {filmes.map((f) => {
            const cinemas = (f.cinemas || '').split(', ').filter(Boolean)
            return (
              <a className="card solo" key={f.id} href={f.url}
                 target="_blank" rel="noopener nofollow">
                <div className="body">
                  <h3 className="title">{f.titulo}</h3>
                  <div className="venue">{f.generos}</div>
                  <div className="meta">
                    <span className="sess">{f.sessoes} sessões</span>
                    {f.duracao_min && <span className="tag tag-src">{f.duracao_min} min</span>}
                    {f.classificacao && <span className="tag tag-src">{f.classificacao}</span>}
                    {f.em_pre_venda === 1 && <span className="tag tag-hot">pré-venda</span>}
                  </div>
                  <div className="cinemas">
                    {cinemas.length} {cinemas.length === 1 ? 'cinema' : 'cinemas'} // {f.cinemas}
                  </div>
                </div>
              </a>
            )
          })}
        </div>
      )}
    </>
  )
}
