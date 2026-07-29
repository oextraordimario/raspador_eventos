import Link from 'next/link'
import { notFound } from 'next/navigation'
import { detalharEvento, slugParaId } from '../../../lib/api'
import { diaSemana, diaMes, horaOuNada, tituloLimpo } from '../../../lib/formato'
import { MARCA, ORIGEM } from '../../../lib/config'
import { Corpo } from './Corpo'

export const revalidate = 300

export async function generateMetadata({ params }) {
  const { id } = await params
  const ev = await detalharEvento(slugParaId(id))
  if (!ev) return { title: 'evento não encontrado' }
  const h = horaOuNada(ev.start_date, ev.fonte)
  const quando = `${diaSemana(ev.start_date)} ${diaMes(ev.start_date)}${h ? `, ${h}` : ''}`
  return {
    title: tituloLimpo(ev.nome),
    description: `${quando} · ${ev.local_nome || MARCA.cidade}. ${ev.descricao?.slice(0, 120) ?? ''}`,
    alternates: { canonical: `${ORIGEM}/evento/${id}` },
  }
}

export default async function Evento({ params }) {
  const { id } = await params
  const ev = await detalharEvento(slugParaId(id))
  if (!ev) notFound()

  const titulo = tituloLimpo(ev.nome)
  const horario = horaOuNada(ev.start_date, ev.fonte)
  // endereço absoluto desta página: o JSON-LD, o link da agenda e o
  // compartilhar apontam todos para cá, e é obrigatório ser um só
  const pagina = `${ORIGEM}/evento/${id}`

  // JSON-LD schema.org/Event — é o que faz a Porta B da Fase 2 existir: o
  // agente e o buscador leem a página como dado estruturado, não como texto.
  // `organizer` fica DE FORA de propósito: o campo às vezes carrega pessoa
  // física, e a API já não o entrega (LGPD).
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Event',
    // nome limpo também aqui: o JSON-LD é o que o agente e o buscador leem, e
    // "Forró na Varanda" descreve o evento melhor que o título com a data
    // repetida que o organizador publicou
    name: titulo,
    startDate: ev.start_date,
    ...(ev.end_date && { endDate: ev.end_date }),
    eventStatus: 'https://schema.org/EventScheduled',
    eventAttendanceMode: 'https://schema.org/OfflineEventAttendanceMode',
    ...(ev.descricao && { description: ev.descricao }),
    location: {
      '@type': 'Place',
      name: ev.local_nome || MARCA.cidade,
      address: {
        '@type': 'PostalAddress',
        ...(ev.endereco && { streetAddress: ev.endereco }),
        ...(ev.bairro && { addressLocality: ev.bairro }),
        addressRegion: ev.estado || 'DF',
        addressCountry: 'BR',
      },
    },
    ...(ev.atracoes && {
      performer: ev.atracoes.split(';').map((n) => ({
        '@type': 'PerformingGroup', name: n.trim(),
      })),
    }),
    ...(ev.preco_min != null && {
      offers: {
        '@type': 'Offer',
        price: ev.preco_min,
        priceCurrency: 'BRL',
        url: ev.url,
        availability: ev.esgotado === 1
          ? 'https://schema.org/SoldOut'
          : 'https://schema.org/InStock',
      },
    }),
    url: pagina,
  }

  return (
    <>
      <script type="application/ld+json"
              dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <Link className="voltar" href="/festas">← voltar</Link>

      <article className="doc">
        <Corpo ev={ev} titulo={titulo} horario={horario} pagina={pagina} />
      </article>
    </>
  )
}
