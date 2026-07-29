import Link from 'next/link'
import { notFound } from 'next/navigation'
import { detalharEvento, slugParaId } from '../../../lib/api'
import { diaSemana, diaMes, horaOuNada, reais, tituloLimpo } from '../../../lib/formato'
import { MARCA, ORIGEM } from '../../../lib/config'
import { TicketCta } from './CtaButton'
import { MapaEmbed, AgendaLink, Compartilhar } from './Acoes'
import { Hero } from '../../Flyer'

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
        <Hero src={ev.imagem} alto={titulo} />

        {/* Capa fica larga (acompanha o .doc inteiro). O resto vira duas
            colunas no desktop — info à esquerda, ingressos/CTA/outros
            botões à direita (`.col-acoes`) — porque numa coluna só a seção
            de ingressos esticava de ponta a ponta. No mobile as duas
            "colunas" empilham normalmente. */}
        <div className="doc-corpo">
          <div className="col-info">
            <h1>{titulo}</h1>
            <div className="when">
              {diaSemana(ev.start_date)} {diaMes(ev.start_date)}
              {horario && ` · ${horario}`}
            </div>
            <div className="where">
              {ev.local_nome || 'local a confirmar'}
              {ev.bairro && ` — ${ev.bairro}`}
              {ev.endereco && <><br /><span className="also">{ev.endereco}</span></>}
            </div>

            {ev.descricao && (
              <div className="sec-sobre">
                <div className="label">sobre</div>
                <div className="desc">{ev.descricao}</div>
                {ev.descricao_truncada && (
                  <div className="desc-corte">
                    Texto do organizador, em trecho — o resto está na página da fonte.
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="col-acoes">
            {ev.lotes?.length > 0 && (
              <div className="sec-ingressos">
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
              </div>
            )}

            <TicketCta href={ev.url} fonte={ev.fonte} haPrice={ev.preco_min != null} />

            <div className="acoes">
              <AgendaLink ev={ev} titulo={titulo} url={pagina} />
              <Compartilhar titulo={titulo} url={pagina} />
            </div>
          </div>

          {/* Filho separado, não dentro de .col-info: no grid de 2 colunas do
              desktop ele tem grid-row/column explícitos (globals.css) pra
              cair embaixo de `.col-info`, sem depender da altura de
              `.col-acoes`. No mobile (flex empilhado) ele é só o último
              item, abaixo de tudo (inclusive dos botões). */}
          <MapaEmbed ev={ev} />
        </div>
      </article>
    </>
  )
}
