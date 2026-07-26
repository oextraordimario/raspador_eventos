import Link from 'next/link'
import { notFound } from 'next/navigation'
import { detalharEvento, slugParaId } from '../../../lib/api'
import { diaSemana, diaMes, hora, reais } from '../../../lib/formato'
import { MARCA, ORIGEM } from '../../../lib/config'

export const revalidate = 300

export async function generateMetadata({ params }) {
  const { id } = await params
  const ev = await detalharEvento(slugParaId(id))
  if (!ev) return { title: 'evento não encontrado' }
  const quando = `${diaSemana(ev.start_date)} ${diaMes(ev.start_date)}, ${hora(ev.start_date)}`
  return {
    title: ev.nome,
    description: `${quando} · ${ev.local_nome || MARCA.cidade}. ${ev.descricao?.slice(0, 120) ?? ''}`,
    alternates: { canonical: `${ORIGEM}/evento/${id}` },
  }
}

export default async function Evento({ params }) {
  const { id } = await params
  const ev = await detalharEvento(slugParaId(id))
  if (!ev) notFound()

  const outras = ev.outras_urls ? ev.outras_urls.split(',').filter(Boolean) : []

  // JSON-LD schema.org/Event — é o que faz a Porta B da Fase 2 existir: o
  // agente e o buscador leem a página como dado estruturado, não como texto.
  // `organizer` fica DE FORA de propósito: o campo às vezes carrega pessoa
  // física, e a API já não o entrega (LGPD).
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Event',
    name: ev.nome,
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
    url: `${ORIGEM}/evento/${id}`,
  }

  return (
    <>
      <script type="application/ld+json"
              dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <Link className="voltar" href="/">&lt; voltar</Link>

      <article className="doc">
        <h1>{ev.nome}</h1>
        <div className="when">
          {diaSemana(ev.start_date)} {diaMes(ev.start_date)} // {hora(ev.start_date)}
        </div>
        <div className="where">
          {ev.local_nome || 'local a confirmar'}
          {ev.bairro && ` — ${ev.bairro}`}
          {ev.endereco && <><br /><span className="also">{ev.endereco}</span></>}
        </div>

        {ev.lotes?.length > 0 && (
          <>
            <div className="label">ingressos</div>
            <div className="box">
              {ev.lotes.map((lo, i) => (
                <div className="row" key={i}>
                  {/* o nome do lote fica CRU, como a fonte publica: a condição
                      ("CORTESIA FEMININA ATÉ 00H") mora nele, de propósito */}
                  <div className="row-name">{lo.nome}</div>
                  <div className={`row-val${lo.gratis ? ' free' : ''}`}>
                    {lo.gratis ? 'grátis' : reais(lo.preco)}
                    {!lo.gratis && lo.taxa > 0 && (
                      <small>inclui {reais(lo.taxa)} de taxa</small>
                    )}
                    {lo.esgotado === 1 && <small>esgotado</small>}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {ev.descricao && (
          <>
            <div className="label">sobre</div>
            <div className="desc">{ev.descricao}</div>
            {ev.descricao_truncada && (
              <div className="desc-corte">
                // texto do organizador, em trecho — o resto está na página da fonte
              </div>
            )}
          </>
        )}

        <a className="cta" href={ev.url} target="_blank" rel="noopener nofollow">
          &gt; abrir no {ev.fonte}
        </a>

        {outras.map((u) => (
          <a key={u} className="cta ghost" href={u} target="_blank" rel="noopener nofollow">
            ver este evento em outra plataforma
          </a>
        ))}
      </article>
    </>
  )
}
