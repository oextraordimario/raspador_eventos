import { API } from './config'

// O id interno é `<fonte>:<id_nativo>` e os dois pontos não vivem bem numa
// rota; `~` é seguro em URL e não aparece em nenhum id das fontes. O id do
// Instagram pode ter dois separadores (instagram:<code>:<n>), então a troca é
// global nos dois sentidos.
export const idParaSlug = (id) => id.replaceAll(':', '~')
export const slugParaId = (slug) => slug.replaceAll('~', ':')

async function buscar(rota, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null && v !== '')
  )
  const url = `${API}/${rota}${qs.toString() ? `?${qs}` : ''}`

  // A API já manda Cache-Control com s-maxage; aqui o revalidate do Next
  // evita ida à função em cada request. A base muda 1x/dia, então 5 min de
  // frescor é folgado — e protege o Neon, que hiberna no free tier.
  //
  // Nunca propaga exceção: página incompleta é ruim, página quebrada é pior.
  // O try/catch cobre falha de REDE (fetch lança, não devolve !ok) — que
  // acontece de verdade em dois momentos: no build, quando a API ainda não
  // está de pé, e em produção quando o Neon está acordando do sono do free
  // tier. Quem chama trata o vazio.
  try {
    const r = await fetch(url, { next: { revalidate: 300 } })
    if (!r.ok) {
      console.error(`API ${rota} respondeu ${r.status}`)
      return null
    }
    return await r.json()
  } catch (e) {
    console.error(`API ${rota} inacessível: ${e.message}`)
    return null
  }
}

export async function listarEventos(params) {
  const r = await buscar('eventos', params)
  return r?.eventos ?? []
}

// A página de festas precisa também das facetas (os dias que o calendário
// habilita), que vêm na mesma resposta — mesmo par que listarFilmes/
// catalogoFilmes, para não mudar o contrato de quem só quer a lista (a home).
export async function catalogoEventos(params) {
  const r = await buscar('eventos', params)
  return { eventos: r?.eventos ?? [], facetas: r?.facetas ?? null }
}

export async function detalharEvento(id) {
  const r = await buscar('evento', { url: id })
  return r && !r.erro ? r : null
}

export async function listarFilmes(params) {
  const r = await buscar('filmes', params)
  return r?.filmes ?? []
}

// A página de cinema precisa também das facetas (valores dos filtros), que
// vêm na mesma resposta — retorno separado do listarFilmes para não mudar o
// contrato de quem só quer a lista (a home).
export async function catalogoFilmes(params) {
  const r = await buscar('filmes', params)
  return { filmes: r?.filmes ?? [], facetas: r?.facetas ?? null }
}

export async function sessoesFilme(filme, params = {}) {
  const r = await buscar('sessoes', { filme, ...params })
  return r && !r.erro ? r : null
}

export async function procedencia() {
  const r = await buscar('procedencia')
  return r?.fontes ?? []
}
