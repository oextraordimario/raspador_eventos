'use client'

import { useEffect, useState } from 'react'
import posthog from 'posthog-js'
import { janelaAgenda } from '../../../lib/formato'

// Ações secundárias do detalhe: situar a pessoa (mapa), levá-la ao calendário
// dela (agenda) e ao amigo dela (compartilhar). Nenhuma pede API, chave ou
// login — agenda e compartilhar são link de template ou API do próprio
// navegador; o mapa usa o embed público do Google Maps (`output=embed`, sem
// chave). São client components só pela instrumentação e, no caso do
// compartilhar, porque o recurso não existe sem JS.

// Mapa: com coordenada, ela vence — o endereço textual das fontes às vezes é
// sujo ("St. Oeste Colonia Colonia Agricola..."), e duas delas não mandam
// endereço nenhum. O fallback textual vira "Casa, Brasília", que é o que a
// casa tem de identificável: pior que coordenada, melhor que nada.
export function MapaEmbed({ ev }) {
  const temCoord = ev.lat != null && ev.lon != null
  const alvo = temCoord
    ? `${ev.lat},${ev.lon}`
    : [ev.local_nome, ev.endereco, ev.cidade].filter(Boolean).join(', ')
  if (!alvo) return null

  const src = `https://www.google.com/maps?q=${encodeURIComponent(alvo)}&output=embed`
  return (
    <div className="mapa-embed">
      <div className="label">mapa</div>
      <iframe src={src} loading="lazy" title="Mapa do local"
              referrerPolicy="no-referrer-when-downgrade" />
    </div>
  )
}

// Google Agenda: `details` leva a NOSSA página, não a da fonte. Não é
// preferência de tráfego — o CTA de compra continua indo para a fonte, no
// mesmo bloco. É que o compromisso do calendário é com quem vai ao evento, e
// a nossa página é a que reúne as plataformas e sobrevive à troca de link.
export function AgendaLink({ ev, titulo, url }) {
  if (!ev.start_date) return null

  const q = new URLSearchParams({
    action: 'TEMPLATE',
    text: titulo,
    dates: janelaAgenda(ev.start_date, ev.end_date),
    details: url,
  })
  const onde = [ev.local_nome, ev.endereco].filter(Boolean).join(', ')
  if (onde) q.set('location', onde)

  return (
    <a className="acao"
       href={`https://calendar.google.com/calendar/render?${q}`}
       target="_blank" rel="noopener"
       onClick={() => posthog.capture('calendar_add_clicked')}>
      adicionar à agenda
    </a>
  )
}

export function Compartilhar({ titulo, url }) {
  // Só aparece depois de montar: sem JS o botão não faz nada, e um botão
  // morto é pior que a ausência dele — a URL da página já é o compartilhamento
  // que sempre funciona.
  const [montado, setMontado] = useState(false)
  const [copiado, setCopiado] = useState(false)
  useEffect(() => setMontado(true), [])
  if (!montado) return null

  const alvo = `${url}?utm_source=share`

  async function clicar() {
    if (navigator.share) {
      try {
        await navigator.share({ title: titulo, url: alvo })
        // depois do await de propósito: compartilhamento cancelado lança
        // AbortError e não deve virar evento de sucesso
        posthog.capture('share_clicked', { method: 'native' })
      } catch { /* cancelou */ }
      return
    }
    try {
      await navigator.clipboard.writeText(alvo)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 2500)
      posthog.capture('share_clicked', { method: 'clipboard' })
    } catch { /* sem permissão de clipboard: nada a fazer */ }
  }

  return (
    <button type="button" className="acao" onClick={clicar}>
      {copiado ? 'link copiado' : 'compartilhar'}
    </button>
  )
}
