'use client'

import posthog from 'posthog-js'

export default function SearchForm({ texto, periodo, gratis }) {
  function handleSubmit(e) {
    const query = e.currentTarget.elements.texto?.value ?? ''
    if (query.trim()) {
      posthog.capture('event_search_performed', { query })
    }
  }

  return (
    <form className="search" action="/festas" onSubmit={handleSubmit}>
      <input name="texto" type="search" defaultValue={texto}
             placeholder="pagode, funk, Ordinário, forró..."
             aria-label="Buscar eventos" />
      {periodo !== 'hoje' && <input type="hidden" name="periodo" value={periodo} />}
      {gratis && <input type="hidden" name="gratis" value="1" />}
    </form>
  )
}
