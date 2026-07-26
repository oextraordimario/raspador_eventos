import { listarEventos, idParaSlug } from '../lib/api'
import { ORIGEM } from '../lib/config'

export const revalidate = 3600

// Passo 5 da spec — a Porta B. Uma página por evento, listada aqui, marcada
// em JSON-LD schema.org/Event na própria página. É o que faz o buscador (e o
// agente que usa busca web) chegar até o conteúdo sem ninguém instalar nada.
//
// Só eventos futuros entram: sitemap com evento de ontem gasta o orçamento de
// rastreamento do buscador em página que já não serve pra nada.
export default async function sitemap() {
  const eventos = await listarEventos({ periodo: '7d', limite: 200 })

  const fixas = ['', '/filmes', '/sobre'].map((p) => ({
    url: `${ORIGEM}${p}`,
    lastModified: new Date(),
    changeFrequency: 'daily',
    priority: p === '' ? 1 : 0.5,
  }))

  return [
    ...fixas,
    ...eventos.map((ev) => ({
      url: `${ORIGEM}/evento/${idParaSlug(ev.id)}`,
      lastModified: new Date(),
      changeFrequency: 'daily',
      priority: 0.8,
    })),
  ]
}
