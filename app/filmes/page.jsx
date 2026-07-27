import Link from 'next/link'
import { catalogoFilmes } from '../../lib/api'
import { MARCA } from '../../lib/config'
import { REDES, HORARIOS, montarFaixas, redesParaCinemas } from '../../lib/cinema'
import FilmCard from './FilmCard'
import Faixa from './Faixa'
import Drop from './Drop'
import Calendario from './Calendario'

export const revalidate = 300

export const metadata = {
  title: 'cinema',
  description: `Filmes em cartaz nos cinemas de ${MARCA.cidade}.`,
}

// Os filtros vivem na URL, como no resto do site (?generos=&classificacao=&
// rede=&cinema=&hora=&texto=). Multi-escolha é CSV no mesmo param. Sem filtro
// nenhum a página é a VITRINE (faixas estilo streaming); qualquer filtro
// ativo troca para a grade plana filtrada — faixa é vitrine, não busca.
export default async function Filmes({ searchParams }) {
  const sp = await searchParams
  const texto = sp?.texto ?? ''
  const generos = (sp?.generos ?? '').split(',').filter(Boolean)
  const classes = (sp?.classificacao ?? '').split(',').filter(Boolean)
  const redes = (sp?.rede ?? '').split(',').filter(Boolean)
  const cinemas = (sp?.cinema ?? '').split(',').filter(Boolean)
  const hora = sp?.hora ?? ''
  // dia local escolhido no calendário (querystring é entrada de estranho)
  const data = /^\d{4}-\d{2}-\d{2}$/.test(sp?.data ?? '') ? sp.data : ''

  const temFiltro = Boolean(texto || generos.length || classes.length ||
                            redes.length || cinemas.length || hora || data)

  // rede e preset de horário são açúcar da UI: viram os params genéricos da
  // API aqui (cinema CSV / hora_de+hora_ate), nunca chegam ao backend.
  const params = { texto, limite: 100 }
  if (generos.length) params.generos = generos.join(',')
  if (classes.length) params.classificacao = classes.join(',')
  if (cinemas.length) params.cinema = cinemas.join(',')
  else if (redes.length) params.cinema = redesParaCinemas(redes).join(',')
  if (hora && HORARIOS[hora]) {
    const h = HORARIOS[hora]
    if (h.hora_de != null) params.hora_de = h.hora_de
    if (h.hora_ate != null) params.hora_ate = h.hora_ate
  }
  // dia do calendário vira a janela de/ate daquele dia LOCAL (Brasília é
  // -03 fixo); o corte é o dia do calendário mesmo, sem a regra das 6h da
  // vida noturna — sessão de cinema pertence ao dia em que começa.
  if (data) {
    params.de = `${data}T00:00:00-03:00`
    params.ate = `${data}T23:59:59-03:00`
  }

  const { filmes, facetas } = await catalogoFilmes(params)

  // Toggle de um valor num filtro preservando os demais. Gêneros,
  // classificação, rede e cinema são listas (CSV na URL); hora é única.
  // Rede e cinema se excluem (os dois viram o MESMO param da API).
  const atual = { texto, generos, classificacao: classes, rede: redes,
                  cinema: cinemas, hora, data }
  const href = (mudanca) => {
    const novo = { ...atual, ...mudanca }
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(novo)) {
      const s = Array.isArray(v) ? v.join(',') : v
      if (s) q.set(k, s)
    }
    const qs = q.toString()
    return qs ? `/filmes?${qs}` : '/filmes'
  }
  const toggleLista = (chave, valor, extra = {}) => {
    const lista = atual[chave]
    return href({
      [chave]: lista.includes(valor)
        ? lista.filter((v) => v !== valor) : [...lista, valor],
      ...extra,
    })
  }

  const nFiltros = generos.length + classes.length + redes.length +
    cinemas.length + (hora ? 1 : 0) + (data ? 1 : 0)
  const faixas = temFiltro ? [] : montarFaixas(filmes)

  return (
    <>
      <div className="secao">
        <h2>cinema</h2>
        <Link href="/">← início</Link>
      </div>

      <div className="filtros">
        <form className="search" action="/filmes">
          <input name="texto" type="search" defaultValue={texto}
                 placeholder="animação, terror, comédia..."
                 aria-label="Buscar filmes" />
        </form>

        <div className="drops" role="group" aria-label="Filtros">
          {facetas?.dias?.length > 0 && (
            <Drop rotulo="data" ativos={data ? 1 : 0} aberto={Boolean(data)}>
              <Calendario dias={facetas.dias} selecionado={data}
                          hrefDia={(dia) => href({ data: data === dia ? '' : dia })} />
            </Drop>
          )}

          {facetas?.generos?.length > 0 && (
            <Drop rotulo="gênero" ativos={generos.length} aberto={generos.length > 0}>
              {facetas.generos.map((g) => (
                <Link key={g} className="chip" href={toggleLista('generos', g)}
                      data-on={generos.includes(g) ? '1' : '0'}>{g}</Link>
              ))}
            </Drop>
          )}

          <Drop rotulo="rede" ativos={redes.length} aberto={redes.length > 0}>
            {Object.entries(REDES).map(([chave, r]) => (
              <Link key={chave} className="chip"
                    href={toggleLista('rede', chave, { cinema: [] })}
                    data-on={redes.includes(chave) ? '1' : '0'}>{r.rotulo}</Link>
            ))}
          </Drop>

          {facetas?.cinemas?.length > 0 && (
            <Drop rotulo="cinema" ativos={cinemas.length} aberto={cinemas.length > 0}>
              {facetas.cinemas.map((c) => (
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

          {facetas?.classificacoes?.length > 0 && (
            <Drop rotulo="classificação" ativos={classes.length} aberto={classes.length > 0}>
              {facetas.classificacoes.map((c) => (
                <Link key={c} className="chip" href={toggleLista('classificacao', c)}
                      data-on={classes.includes(c) ? '1' : '0'}>{c}</Link>
              ))}
            </Drop>
          )}

          {nFiltros > 0 && (
            <Link className="drop-limpar"
                  href={texto ? `/filmes?texto=${encodeURIComponent(texto)}` : '/filmes'}>
              limpar
            </Link>
          )}
        </div>
      </div>

      {temFiltro ? (
        <>
          <p className="count">
            {filmes.length} {filmes.length === 1 ? 'filme' : 'filmes'}
          </p>
          {filmes.length === 0 ? (
            <div className="empty">
              <strong>Nada em cartaz com esses filtros</strong>
              <span>
                {texto ? `Nenhum filme casa com “${texto}”.` : 'Afrouxe um dos filtros.'}
              </span>
            </div>
          ) : (
            <div className="list">
              {filmes.map((f) => <FilmCard key={f.id} filme={f} />)}
            </div>
          )}
        </>
      ) : filmes.length === 0 ? (
        <div className="empty">
          <strong>Nada em cartaz</strong>
          <span>A grade ainda não foi coletada.</span>
        </div>
      ) : (
        <div className="vitrine">
          {faixas.map((fx, i) => (
            <Faixa key={fx.chave} titulo={fx.titulo} filmes={fx.filmes}
                   prioridade={i === 0} />
          ))}
        </div>
      )}
    </>
  )
}
