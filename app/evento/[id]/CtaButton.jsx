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
      &gt; abrir no {fonte}
    </a>
  )
}

export function OtherPlatformCta({ href }) {
  function handleClick() {
    posthog.capture('other_platform_link_clicked')
  }

  return (
    <a className="cta ghost" href={href} target="_blank" rel="noopener nofollow"
       onClick={handleClick}>
      ver este evento em outra plataforma
    </a>
  )
}
