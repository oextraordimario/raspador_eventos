'use client'

import posthog from 'posthog-js'

export default function FilmCard({ filme }) {
  const cinemas = (filme.cinemas || '').split(', ').filter(Boolean)

  function handleClick() {
    posthog.capture('film_link_clicked', {
      film_title: filme.titulo,
      film_genres: filme.generos,
      session_count: filme.sessoes,
    })
  }

  return (
    <a className="card solo" href={filme.url} target="_blank" rel="noopener nofollow"
       onClick={handleClick}>
      <div className="body">
        <h3 className="title">{filme.titulo}</h3>
        <div className="venue">{filme.generos}</div>
        <div className="meta">
          <span className="sess">{filme.sessoes} sessões</span>
          {filme.duracao_min && <span className="tag tag-src">{filme.duracao_min} min</span>}
          {filme.classificacao && <span className="tag tag-src">{filme.classificacao}</span>}
          {filme.em_pre_venda === 1 && <span className="tag tag-hot">pré-venda</span>}
        </div>
        <div className="cinemas">
          {cinemas.length} {cinemas.length === 1 ? 'cinema' : 'cinemas'} · {filme.cinemas}
        </div>
      </div>
    </a>
  )
}
