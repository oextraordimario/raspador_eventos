'use client'

import posthog from 'posthog-js'
import { hora } from '../../../lib/formato'

// O clique que vale: horário → checkout da fonte. O evento substitui o
// antigo film_link_clicked do card (que agora abre o detalhe interno) — é
// aqui que se mede se o funil novo (site → detalhe → compra) segura o clique.
export default function SessaoLink({ sessao, filme }) {
  function handleClick() {
    posthog.capture('film_session_clicked', {
      film_title: filme,
      cinema: sessao.cinema,
      session_time: sessao.inicio,
      session_types: sessao.tipos,
    })
  }
  // O formato (Dublado/3D/...) fica no rótulo da linha, não na pill — só a
  // hora é clicável; o tipo segue indo no evento de telemetria.
  return (
    <a className="horario" href={sessao.url_compra || undefined}
       target="_blank" rel="noopener nofollow" onClick={handleClick}>
      <span className="horario-hora">{hora(sessao.inicio)}</span>
    </a>
  )
}
