import Link from 'next/link'
import { notFound } from 'next/navigation'
import { sessoesFilme } from '../../../lib/api'
import { ORIGEM } from '../../../lib/config'
import { chaveDia, rotuloDia, diaMes } from '../../../lib/formato'
import { REDES, HORARIOS, redesParaCinemas, notaFmt } from '../../../lib/cinema'
import Cartaz from '../Cartaz'
import DropFiltro from '../DropFiltro'
import SessaoLink from './SessaoLink'

export const revalidate = 300

export async function generateMetadata({ params }) {
  const { id } = await params
  const filme = await sessoesFilme(id)
  if (!filme) return { title: 'filme não encontrado' }
  return {
    title: filme.titulo,
    description: `Sessões de ${filme.titulo} nos cinemas de Brasília — horários, salas e onde comprar.`,
  }
}

// Agrupa as sessões por cinema e, dentro dele, por dia local — a pergunta da
// pessoa é "onde e quando eu consigo ver", nessa ordem.
function porCinema(sessoes) {
  const cinemas = new Map()
  for (const s of sessoes) {
    if (!cinemas.has(s.cinema)) cinemas.set(s.cinema, new Map())
    const dias = cinemas.get(s.cinema)
    const dia = chaveDia(s.inicio)
    if (!dias.has(dia)) dias.set(dia, [])
    dias.get(dia).push(s)
  }
  return [...cinemas.entries()].map(([cinema, dias]) => ({
    cinema,
    dias: [...dias.entries()].map(([dia, lista]) => ({ dia, sessoes: lista })),
  }))
}

export default async function Filme({ params, searchParams }) {
  const { id } = await params
  const sp = await searchParams

  // Mesmos filtros da lista (menos gênero/classificação, que não fazem
  // sentido num filme só): ajudam a achar o lugar e a hora certos de ver
  // ESTE filme. Vivem na URL e descem como params genéricos da API.
  const redes = (sp?.rede ?? '').split(',').filter(Boolean)
  const cinemas = (sp?.cinema ?? '').split(',').filter(Boolean)
  const hora = sp?.hora ?? ''
  const paramsApi = {}
  if (cinemas.length) paramsApi.cinema = cinemas.join(',')
  else if (redes.length) paramsApi.cinema = redesParaCinemas(redes).join(',')
  if (hora && HORARIOS[hora]) {
    const h = HORARIOS[hora]
    if (h.hora_de != null) paramsApi.hora_de = h.hora_de
    if (h.hora_ate != null) paramsApi.hora_ate = h.hora_ate
  }

  const filme = await sessoesFilme(id, paramsApi)
  if (!filme) notFound()

  const grade = porCinema(filme.sessoes || [])
  const temFiltro = redes.length > 0 || cinemas.length > 0 || Boolean(hora)

  // estado atual da URL, p/ o "aplicar" dos DropFiltro preservar os demais
  const estado = { rede: redes.join(','), cinema: cinemas.join(','), hora }

  // só as redes com cinema onde o filme passa viram opção
  const redesDoFilme = Object.entries(REDES).filter(([, r]) =>
    (filme.cinemas || []).some((c) => r.cinemas.some((p) => c.startsWith(p))))

  // JSON-LD schema.org/Movie — a Porta B da Fase 2 vale para o cinema também.
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Movie',
    name: filme.titulo,
    ...(filme.generos && { genre: filme.generos.split(',').map((g) => g.trim()) }),
    ...(filme.duracao_min && { duration: `PT${filme.duracao_min}M` }),
    ...(filme.classificacao && { contentRating: filme.classificacao }),
    ...(filme.poster && { image: filme.poster }),
    ...(filme.trailer && { trailer: { '@type': 'VideoObject', url: filme.trailer } }),
    ...(filme.sinopse && { description: filme.sinopse }),
    ...(filme.nota != null && filme.votos && {
      aggregateRating: { '@type': 'AggregateRating', ratingValue: filme.nota,
                         bestRating: 10, ratingCount: filme.votos },
    }),
    ...(filme.tmdb_id && {
      sameAs: `https://www.themoviedb.org/movie/${filme.tmdb_id}`,
    }),
    url: `${ORIGEM}/filmes/${filme.id}`,
  }

  return (
    <>
      <script type="application/ld+json"
              dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <Link className="voltar" href="/filmes">← voltar</Link>

      <article className="doc filme-doc">
        <div className="filme-topo">
          <div className="filme-cartaz">
            <Cartaz src={filme.poster_proprio || filme.poster} titulo={filme.titulo}
                    tamanhos="(min-width: 900px) 220px, 40vw" prioridade />
          </div>
          <div className="filme-info">
            <h1>{filme.titulo}</h1>
            <p className="filme-generos">
              {[filme.ano, filme.generos].filter(Boolean).join(' · ')}
            </p>
            <div className="meta">
              {filme.nota != null && (
                <span className="nota">★ {notaFmt(filme.nota)}
                  {filme.tmdb_id ? (
                    <a className="nota-fonte"
                       href={`https://www.themoviedb.org/movie/${filme.tmdb_id}`}
                       target="_blank" rel="noopener nofollow"> tmdb ↗</a>
                  ) : filme.votos ? <span className="nota-fonte"> tmdb</span> : null}
                </span>
              )}
              {filme.duracao_min && <span className="tag tag-src">{filme.duracao_min} min</span>}
              {filme.classificacao && <span className="tag tag-src">{filme.classificacao}</span>}
              {filme.em_pre_venda === 1 && <span className="tag tag-hot">pré-venda</span>}
            </div>
            {filme.sinopse && <p className="filme-sinopse">{filme.sinopse}</p>}
            {/* O embed do trailer foi testado e rejeitado (27/07, "ficou
                palha") — voltou a link externo até um layout melhor. */}
            {filme.trailer && (
              <p>
                <a className="filme-trailer" href={filme.trailer} target="_blank"
                   rel="noopener nofollow">▶ assistir ao trailer</a>
              </p>
            )}
          </div>
        </div>

        <hr className="filme-divisor" />

        <h2>encontre sua sessão</h2>

        <div className="drops" role="group" aria-label="Filtrar sessões">
          {redesDoFilme.length > 1 && (
            <DropFiltro rotulo="rede" base={`/filmes/${id}`} estado={estado}
                        param="rede" selecionados={redes} limpa="cinema"
                        opcoes={redesDoFilme.map(([chave, r]) =>
                          ({ valor: chave, rotulo: r.rotulo }))} />
          )}
          {(filme.cinemas || []).length > 1 && (
            <DropFiltro rotulo="cinema" base={`/filmes/${id}`} estado={estado}
                        param="cinema" selecionados={cinemas} limpa="rede"
                        opcoes={filme.cinemas.map((c) => ({ valor: c, rotulo: c }))} />
          )}
          <DropFiltro rotulo="horário" base={`/filmes/${id}`} estado={estado}
                      param="hora" selecionados={hora ? [hora] : []} unico
                      opcoes={Object.entries(HORARIOS).map(([chave, h]) =>
                        ({ valor: chave, rotulo: h.rotulo }))} />
          {temFiltro && (
            <Link className="drop-limpar" href={`/filmes/${id}`}>limpar</Link>
          )}
        </div>

        {grade.length === 0 ? (
          <div className="empty">
            <strong>{temFiltro ? 'Nenhuma sessão com esses filtros' : 'Sem sessões futuras'}</strong>
            <span>
              {temFiltro
                ? 'Afrouxe um dos filtros — as opções acima mostram onde o filme passa.'
                : 'O filme saiu de cartaz ou a grade ainda não foi coletada.'}
            </span>
          </div>
        ) : (
          grade.map(({ cinema, dias }) => (
            <div className="box sess-cinema" key={cinema}>
              <div className="row sess-cinema-nome">{cinema}</div>
              {dias.map(({ dia, sessoes }) => {
                const r = rotuloDia(dia)
                return (
                  <div className="row sess-dia" key={dia}>
                    <span className="sess-dia-rotulo">
                      {r.texto} <span className="num">{diaMes(`${dia}T12:00:00-03:00`)}</span>
                    </span>
                    <span className="horarios">
                      {sessoes.map((s) => (
                        <SessaoLink key={s.inicio + (s.sala || '')} sessao={s}
                                    filme={filme.titulo} />
                      ))}
                    </span>
                  </div>
                )
              })}
            </div>
          ))
        )}

        <div className="note">
          Não vendemos ingresso: cada horário aponta para a plataforma que está
          vendendo (Ingresso.com). Preço e disponibilidade são de lá.
        </div>
      </article>
    </>
  )
}
