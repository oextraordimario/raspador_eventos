'use client'

import posthog from 'posthog-js'

export function TicketCta({ href, fonte, haPrice }) {
  function handleClick() {
    posthog.capture('ticket_link_clicked', {
      event_source: fonte,
      has_price: haPrice,
    })
  }

  return (
    <a className="cta" href={href} target="_blank" rel="noopener nofollow"
       onClick={handleClick}>
      {/* Sem preço não há o que comprar — no Instagram, por exemplo, a fonte é
          um post, não uma bilheteria. Prometer "comprar" ali seria mentira. */}
      {haPrice ? `Comprar no ${fonte}` : `Ver no ${fonte}`}
    </a>
  )
}
