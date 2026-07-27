import Link from 'next/link'
import { notFound } from 'next/navigation'
import { sessoesFilme } from '../../../lib/api'
import { ORIGEM } from '../../../lib/config'
import { chaveDia, rotuloDia, diaMes } from '../../../lib/formato'
import { REDES, HORARIOS, redesParaCinemas } from '../../../lib/cinema'
import Cartaz from '../Cartaz'
import Drop from '../Drop'
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

  const atual = { rede: redes, cinema: cinemas, hora }
  const href = (mudanca) => {
    const novo = { ...atual, ...mudanca }
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(novo)) {
      const s = Array.isArray(v) ? v.join(',') : v
      if (s) q.set(k, s)
    }
    const qs = q.toString()
    return qs ? `/filmes/${id}?${qs}` : `/filmes/${id}`
  }
  const toggleLista = (chave, valor, extra = {}) => {
    const lista = atual[chave]
    return href({
      [chave]: lista.includes(valor)
        ? lista.filter((v) => v !== valor) : [...lista, valor],
      ...extra,
    })
  }

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
            <Cartaz src={filme.poster} titulo={filme.titulo}
                    tamanhos="(min-width: 900px) 220px, 40vw" prioridade />
          </div>
          <div className="filme-info">
            <h1>{filme.titulo}</h1>
            {filme.generos && <p className="filme-generos">{filme.generos}</p>}
            <div className="meta">
              {filme.duracao_min && <span className="tag tag-src">{filme.duracao_min} min</span>}
              {filme.classificacao && <span className="tag tag-src">{filme.classificacao}</span>}
              {filme.em_pre_venda === 1 && <span className="tag tag-hot">pré-venda</span>}
            </div>
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

        <div className="label">Sessões — cada horário leva à compra na fonte</div>

        <div className="drops" role="group" aria-label="Filtrar sessões">
          {redesDoFilme.length > 1 && (
            <Drop rotulo="rede" ativos={redes.length} aberto={redes.length > 0}>
              {redesDoFilme.map(([chave, r]) => (
                <Link key={chave} className="chip"
                      href={toggleLista('rede', chave, { cinema: [] })}
                      data-on={redes.includes(chave) ? '1' : '0'}>{r.rotulo}</Link>
              ))}
            </Drop>
          )}
          {(filme.cinemas || []).length > 1 && (
            <Drop rotulo="cinema" ativos={cinemas.length} aberto={cinemas.length > 0}>
              {filme.cinemas.map((c) => (
                <Link key={c} className="chip"
                      href={toggleLista('cinema', c, { rede: [] })}
                      data-on={cinemas.includes(c) ? '1' : '0'}>{c}</Link>
              ))}
            </Drop>
          )}
          <Drop rotulo="horário" ativos={hora ? 1 : 0} aberto={Boolean(hora)}>
            {Object.entries(HORARIOS).map(([chave, h]) => (
              <Link key={chave} className="chip"
                    href={href({ hora: hora === chave ? '' : chave })}
                    data-on={hora === chave ? '1' : '0'}>{h.rotulo}</Link>
            ))}
          </Drop>
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
