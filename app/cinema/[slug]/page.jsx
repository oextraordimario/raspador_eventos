import Link from 'next/link'
import { notFound, permanentRedirect } from 'next/navigation'
import { sessoesFilme } from '../../../lib/api'
import { ORIGEM } from '../../../lib/config'
import { chaveDia, rotuloDia, diaMes } from '../../../lib/formato'
import { REDES, HORARIOS, redesParaCinemas, notaFmt } from '../../../lib/cinema'
import Cartaz from '../Cartaz'
import Drop from '../../Drop'
import DropFiltro from '../../DropFiltro'
import Calendario from '../../Calendario'
import SessaoLink from './SessaoLink'

export const revalidate = 300

export async function generateMetadata({ params }) {
  const { slug } = await params
  const filme = await sessoesFilme(slug)
  if (!filme) return { title: 'filme não encontrado' }
  return {
    title: filme.titulo,
    description: `Sessões de ${filme.titulo} nos cinemas de Brasília: horários, salas e onde comprar.`,
    // como na página de evento: o canônico é o slug do filme, não o parâmetro
    // pelo qual se chegou (id numérico antigo, ou slug sem o ano)
    alternates: { canonical: `${ORIGEM}/cinema/${filme.slug}` },
  }
}

// A grade mostra UM dia por vez (o da strip): dentro do dia, agrupa por
// cinema e, dentro dele, por formato ("Dublado", "3D/Legendado") — o rótulo
// aparece uma vez por linha e as pills ficam só com a hora. Tudo expandido
// (8 dias × 6 cinemas) era um paredão de 559 pills.
function porCinemaTipo(sessoes) {
  const cinemas = new Map()
  for (const s of sessoes) {
    if (!cinemas.has(s.cinema)) cinemas.set(s.cinema, new Map())
    const tipos = cinemas.get(s.cinema)
    const tipo = s.tipos || 'sessão'
    if (!tipos.has(tipo)) tipos.set(tipo, [])
    tipos.get(tipo).push(s)
  }
  return [...cinemas.entries()].map(([cinema, tipos]) => ({
    cinema,
    tipos: [...tipos.entries()]
      .map(([tipo, lista]) => ({
        tipo,
        sessoes: [...lista].sort((a, b) => (a.inicio < b.inicio ? -1 : 1)),
      }))
      .sort((a, b) => (a.sessoes[0].inicio < b.sessoes[0].inicio ? -1 : 1)),
  }))
}

export default async function Filme({ params, searchParams }) {
  const { slug } = await params
  const sp = await searchParams

  // Mesmos filtros da lista (menos gênero/classificação, que não fazem
  // sentido num filme só): ajudam a achar o lugar e a hora certos de ver
  // ESTE filme. Vivem na URL e descem como params genéricos da API.
  const redes = (sp?.rede ?? '').split(',').filter(Boolean)
  const cinemas = (sp?.cinema ?? '').split(',').filter(Boolean)
  const audios = (sp?.audio ?? '').split(',').filter(Boolean)
  const hora = sp?.hora ?? ''
  // dia da strip (querystring é entrada de estranho, valida o formato)
  const data = /^\d{4}-\d{2}-\d{2}$/.test(sp?.data ?? '') ? sp.data : ''
  const paramsApi = {}
  if (cinemas.length) paramsApi.cinema = cinemas.join(',')
  else if (redes.length) paramsApi.cinema = redesParaCinemas(redes).join(',')
  if (audios.length) paramsApi.audio = audios.join(',')
  if (hora && HORARIOS[hora]) {
    const h = HORARIOS[hora]
    if (h.hora_de != null) paramsApi.hora_de = h.hora_de
    if (h.hora_ate != null) paramsApi.hora_ate = h.hora_ate
  }

  const filme = await sessoesFilme(slug, paramsApi)
  if (!filme) notFound()

  // Mesma regra da página de evento (uma só, sem farejar formato): id numérico
  // antigo (`/cinema/29922`), slug sem o ano (compartilhado antes de o TMDB
  // responder) e título casado por ILIKE todos chegam aqui e vão de 308 para o
  // endereço de hoje. Guarda contra laço: só redireciona se houver slug e ele
  // for diferente.
  if (filme.slug && filme.slug !== slug) permanentRedirect(`/cinema/${filme.slug}`)

  // Os dias vêm do conjunto JÁ filtrado (rede/cinema/hora cortam via API):
  // se um filtro esvazia um dia, ele some da strip. Dia da URL que não
  // existe mais cai no primeiro disponível — a strip nunca aponta pro vazio.
  const todas = filme.sessoes || []
  const dias = [...new Set(todas.map((s) => chaveDia(s.inicio)))].sort()
  const diaSel = dias.includes(data) ? data : dias[0]
  const grade = porCinemaTipo(todas.filter((s) => chaveDia(s.inicio) === diaSel))
  const temFiltro = redes.length > 0 || cinemas.length > 0 ||
                    audios.length > 0 || Boolean(hora)

  // Quantos meses a grade encosta: decide só a largura do menu (um calendário
  // ou dois lado a lado), não o que o Calendario mostra.
  const meses = new Set(dias.map((d) => d.slice(0, 7))).size
  // O rótulo do drop carrega o dia que está na tela. Colapsar a strip sem
  // isso tiraria da página a única indicação de QUAL dia a grade abaixo é.
  const rotuloData = diaSel
    ? `${rotuloDia(diaSel).texto} ${diaMes(`${diaSel}T12:00:00-03:00`)}`
    : 'data'

  // estado atual da URL, p/ a strip e o "aplicar" dos DropFiltro preservarem
  // os demais parâmetros ao navegar
  const estado = { rede: redes.join(','), cinema: cinemas.join(','),
                   audio: audios.join(','), hora, data }
  const hrefDia = (dia) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries({ ...estado, data: dia })) if (v) q.set(k, v)
    return `/cinema/${filme.slug}?${q.toString()}`
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
    ...(filme.sinopse && { description: filme.sinopse }),
    ...(filme.nota != null && filme.votos && {
      aggregateRating: { '@type': 'AggregateRating', ratingValue: filme.nota,
                         bestRating: 10, ratingCount: filme.votos },
    }),
    ...(filme.tmdb_id && {
      sameAs: `https://www.themoviedb.org/movie/${filme.tmdb_id}`,
    }),
    url: `${ORIGEM}/cinema/${filme.slug}`,
  }

  return (
    <>
      <script type="application/ld+json"
              dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <Link className="voltar" href="/cinema">← voltar</Link>

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
          {/* A strip de abas de dia virou um drop só, com o mesmo calendário
              das páginas de lista. Sem setas de mês de propósito: a grade da
              fonte cobre ~8 dias, então `maxMeses=0` (o default do
              Calendario) mostra exatamente os meses que existem — um, ou dois
              quando a semana atravessa a virada. Navegar para um mês vazio
              não teria o que mostrar. */}
          {dias.length > 0 && (
            <Drop rotulo={rotuloData} aberto={Boolean(data)}
                  classeMenu={meses > 1 ? 'drop-menu-data' : ''}>
              <Calendario dias={dias} selecionado={diaSel} hrefDia={hrefDia} />
            </Drop>
          )}

          {/* Quando e a que horas andam juntos: são as duas perguntas que a
              pessoa faz antes de escolher ONDE. */}
          <DropFiltro rotulo="horário" base={`/cinema/${filme.slug}`} estado={estado}
                      param="hora" selecionados={hora ? [hora] : []} unico
                      opcoes={Object.entries(HORARIOS).map(([chave, h]) =>
                        ({ valor: chave, rotulo: h.rotulo }))} />

          {/* As opções saem do que ESTE filme tem (mesmo contrato de
              `filme.cinemas`: a lista vem sem os filtros aplicados). Filme
              nacional costuma ter só "Nacional" — aí o drop não aparece. */}
          {(filme.audios || []).length > 1 && (
            <DropFiltro rotulo="áudio" base={`/cinema/${filme.slug}`} estado={estado}
                        param="audio" selecionados={audios}
                        opcoes={filme.audios.map((a) => ({ valor: a, rotulo: a }))} />
          )}

          {redesDoFilme.length > 1 && (
            <DropFiltro rotulo="rede" base={`/cinema/${filme.slug}`} estado={estado}
                        param="rede" selecionados={redes} limpa="cinema"
                        opcoes={redesDoFilme.map(([chave, r]) =>
                          ({ valor: chave, rotulo: r.rotulo }))} />
          )}
          {(filme.cinemas || []).length > 1 && (
            <DropFiltro rotulo="cinema" base={`/cinema/${filme.slug}`} estado={estado}
                        param="cinema" selecionados={cinemas} limpa="rede"
                        opcoes={filme.cinemas.map((c) => ({ valor: c, rotulo: c }))} />
          )}
          {temFiltro && (
            <Link className="drop-limpar"
                  href={data ? `/cinema/${filme.slug}?data=${data}` : `/cinema/${filme.slug}`}>
              limpar
            </Link>
          )}
        </div>

        {grade.length === 0 ? (
          <div className="empty">
            <strong>{temFiltro ? 'Nenhuma sessão com esses filtros' : 'Sem sessões futuras'}</strong>
            <span>
              {temFiltro
                ? 'Afrouxe um dos filtros: as opções acima mostram onde o filme passa.'
                : 'O filme saiu de cartaz, ou ainda não coletamos a grade desta semana.'}
            </span>
          </div>
        ) : (
          grade.map(({ cinema, tipos }) => (
            <div className="box sess-cinema" key={cinema}>
              <div className="row sess-cinema-nome">{cinema}</div>
              {tipos.map(({ tipo, sessoes }) => (
                <div className="row sess-tipo" key={tipo}>
                  <span className="sess-tipo-rotulo">{tipo}</span>
                  <span className="horarios">
                    {sessoes.map((s) => (
                      <SessaoLink key={s.inicio + (s.sala || '')} sessao={s}
                                  filme={filme.titulo} />
                    ))}
                  </span>
                </div>
              ))}
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
