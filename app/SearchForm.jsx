'use client'

import posthog from 'posthog-js'

// `periodo` aqui é o da URL, não o resolvido pela página — a diferença é o
// NI-41. Buscar a partir do estado default tem que produzir URL SEM
// `?periodo=`, porque é a ausência dele que deixa a busca escolher a janela
// certa (config.periodoPadrao). Propagar o período resolvido prenderia toda
// busca no "hoje" e reabriria o bug.
export default function SearchForm({ texto, periodo, gratis, dia }) {
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
      {periodo && <input type="hidden" name="periodo" value={periodo} />}
      {gratis && <input type="hidden" name="gratis" value="1" />}
      {/* buscar DENTRO do dia escolhido — sem isto, digitar um termo jogaria
          a pessoa de volta para a agenda inteira sem ela ter pedido */}
      {dia && <input type="hidden" name="dia" value={dia} />}
    </form>
  )
}
