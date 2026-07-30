import Link from 'next/link'
import { notFound, permanentRedirect } from 'next/navigation'
import { detalharEvento } from '../../../lib/api'
import { diaSemana, diaMes, horaOuNada } from '../../../lib/formato'
import { MARCA, ORIGEM } from '../../../lib/config'
import { Corpo } from './Corpo'

export const revalidate = 300

export async function generateMetadata({ params }) {
  const { slug } = await params
  const ev = await detalharEvento(slug)
  if (!ev) return { title: 'evento não encontrado' }
  const h = horaOuNada(ev.start_date, ev.fonte)
  const quando = `${diaSemana(ev.start_date)} ${diaMes(ev.start_date)}${h ? `, ${h}` : ''}`
  return {
    title: ev.nome,
    description: `${quando} · ${ev.local_nome || MARCA.cidade}. ${ev.descricao?.slice(0, 120) ?? ''}`,
    // o canônico sai do SLUG do evento, nunca do parâmetro da rota: chegar por
    // um endereço antigo não pode fazer esse endereço se declarar canônico
    alternates: { canonical: `${ORIGEM}/evento/${ev.slug}` },
  }
}

export default async function Evento({ params }) {
  const { slug } = await params
  const ev = await detalharEvento(slug)
  if (!ev) notFound()

  // UMA regra cobre todo endereço que não é o de hoje, sem farejar formato:
  // id antigo (`sympla~3520331`), slug de antes de um renome, e o caso da
  // duplicata — em que a API responde o evento CANÔNICO, cujo slug é outro.
  // Esse último era um bug silencioso até aqui: a página servia o conteúdo do
  // canônico num endereço próprio, e o buscador via conteúdo duplicado com o
  // `canonical` apontando para o lugar errado.
  // `ev.slug` nulo (tratamento ainda não passou) não redireciona — é a guarda
  // que impede laço.
  if (ev.slug && ev.slug !== slug) permanentRedirect(`/evento/${ev.slug}`)

  // O nome já vem limpo da BASE (NI-33, 2026-07-29): a regra que remove a data
  // que o organizador repetiu no título mora em `base/texto.py` e roda na
  // escrita da prata, então o <h1>, o slug, o FTS e o que o agente do MCP
  // recebe são a mesma string. Antes disso, `tituloLimpo()` consertava só aqui.
  const titulo = ev.nome
  const horario = horaOuNada(ev.start_date, ev.fonte)
  // endereço absoluto desta página: o JSON-LD, o link da agenda e o
  // compartilhar apontam todos para cá, e é obrigatório ser um só
  const pagina = `${ORIGEM}/evento/${ev.slug}`

  // JSON-LD schema.org/Event — é o que faz a Porta B da Fase 2 existir: o
  // agente e o buscador leem a página como dado estruturado, não como texto.
  // `organizer` fica DE FORA de propósito: o campo às vezes carrega pessoa
  // física, e a API já não o entrega (LGPD).
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Event',
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
