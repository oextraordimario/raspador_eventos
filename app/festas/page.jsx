import { Suspense } from 'react'
import Link from 'next/link'
import { catalogoEventos, procedencia, idParaSlug } from '../../lib/api'
import Esqueleto from '../Esqueleto'
import { agruparPorDia, rotuloDia, diaMes, horaOuNada, reais, tituloLimpo } from '../../lib/formato'
import { MARCA, PERIODOS, periodoPadrao } from '../../lib/config'
import Procedencia from '../Procedencia'
import SearchForm from '../SearchForm'
import Flyer from '../Flyer'
import Drop from '../Drop'
import Calendario from '../Calendario'

// Um dia escolhido no calendário vira a janela daquele dia LOCAL (Brasília é
// -03 fixo) e SUBSTITUI o atalho de período — os dois respondem à mesma
// pergunta, e deixar os dois valendo produziria interseções vazias sem que a
// pessoa entendesse por quê.
function paramsDe({ periodo, texto, gratis, dia }) {
  const p = { texto, gratis: gratis ? '1' : '' }
  if (dia) {
    p.de = `${dia}T00:00:00-03:00`
    p.ate = `${dia}T23:59:59-03:00`
  } else {
    p.periodo = periodo
  }
  return p
}

// Os filtros vivem na URL (?periodo=&texto=&gratis=), não em estado de
// cliente. Três ganhos que importam aqui: a página funciona sem JS, cada
// combinação é um endereço compartilhável, e o SSR entrega HTML pronto — que é
// o que a Fase 2 precisa que o buscador e o agente leiam.
export const revalidate = 300

export const metadata = {
  title: 'festas & shows',
  description: `Festas, shows e baladas em ${MARCA.cidade}, com preço, line-up e link para o ingresso.`,
}

// As quatro primeiras imagens carregam com prioridade: são as que ocupam a
// tela na abertura, e é nelas que a página é julgada como rápida ou lenta.
const PRIORITARIAS = 4

function Card({ ev, indice }) {
  const gratis = ev.tem_gratis === 1
  const titulo = tituloLimpo(ev.nome)
  const quando = horaOuNada(ev.start_date, ev.fonte)
  return (
    <Link className="card" href={`/evento/${idParaSlug(ev.id)}`}>
      <Flyer src={ev.imagem} alto={titulo}
             tamanhos="(min-width: 900px) 92px, 78px"
             prioridade={indice < PRIORITARIAS} />
      <div className="body">
        <h3 className="title">{titulo}</h3>
        <div className="venue">
          {ev.local_nome || 'local a confirmar'}
          {ev.bairro && <><span className="sep">·</span>{ev.bairro}</>}
        </div>
        {ev.atracoes && (
          <div className="lineup">{ev.atracoes.split(';').join(' · ')}</div>
        )}
        {/* NI-38: o resumo entra na mesma posição da sinopse do card de filme
            (título > local > resumo > meta) e com o mesmo corte de 2 linhas —
            que é do CSS, não de JS: o trecho de 600 chars da API é sobra. Sem
            descrição, nada renderiza: placeholder aqui só faria barulho. */}
        {ev.descricao && <div className="resumo">{ev.descricao}</div>}
        <div className="meta">
          {quando && <span className="time">{quando}</span>}
          {ev.preco_min != null ? (
            <span className="price">
              <span className="from">a partir de</span>{reais(ev.preco_min)}
            </span>
          ) : gratis ? (
            <span className="tag tag-free">grátis</span>
          ) : (
            <span className="price none">preço não informado</span>
          )}
          {ev.preco_min != null && gratis && (
            <span className="tag tag-free">tem cortesia</span>
          )}
          {ev.esgotado === 1 && <span className="tag tag-out">esgotado</span>}
          {ev.fonte && <span className="tag tag-src">{ev.fonte}</span>}
        </div>
        {ev.outras_urls && (
          <div className="also">também em outra plataforma</div>
        )}
      </div>
    </Link>
  )
}

// A parte da página que DEPENDE da base, separada do resto de propósito: é o
// que o <Suspense> de baixo consegue trocar por um esqueleto sem levar junto o
// cabeçalho e os filtros — que devem continuar na tela, e clicáveis, enquanto
// o resultado novo não chega.
async function Resultado({ periodo, texto, gratis, dia }) {
  const [{ eventos }, fontes] = await Promise.all([
    catalogoEventos(paramsDe({ periodo, texto, gratis, dia })),
    procedencia(),
  ])
  const grupos = agruparPorDia(eventos)

  return (
    <>
      <p className="count">
        {eventos.length} {eventos.length === 1 ? 'evento' : 'eventos'}
      </p>

      {grupos.length === 0 ? (
        <div className="empty">
          <strong>Nada por aqui</strong>
          <span>
            {texto
              ? periodo === 'proximos'
                // já é a janela mais larga que existe: sugerir "amplie o
                // período" seria mandar a pessoa fazer o que ela já fez
                ? `Nenhum resultado para “${texto}” na agenda inteira. Tente outro termo.`
                : `Nenhum resultado para “${texto}”. Tente outro termo ou amplie o período.`
              : 'Amplie o período ou tire o filtro de grátis.'}
          </span>
        </div>
      ) : (
        <div className="list">
          {(() => {
            // Índice contínuo através dos grupos: quem decide o carregamento
            // prioritário é a posição na TELA, não a posição dentro do dia.
            let n = 0
            return grupos.map((g) => {
              const r = rotuloDia(g.chave)
              return (
                <div key={g.chave} style={{ display: 'contents' }}>
                  <div className={`day${r.hoje ? ' hoje' : ''}`}>
                    <div className="day-label">
                      {r.texto}
                      <span className="num">{diaMes(`${g.chave}T12:00:00-03:00`)}</span>
                    </div>
                    <div className="day-rule" />
                  </div>
                  {g.eventos.map((ev) => <Card key={ev.id} ev={ev} indice={n++} />)}
                </div>
              )
            })
          })()}
        </div>
      )}

      <Procedencia fontes={fontes} />
    </>
  )
}

// Quantos meses o calendário mostra de uma vez. A agenda alcança meses; três
// blocos ainda se leem como calendário, seis viram rolagem. O que passa disso
// não some — vira a linha "+ N dias depois de <mês>".
const MESES_NO_CALENDARIO = 3

// O calendário é o único filtro que depende da base (precisa saber que dias
// têm evento), então ele suspende sozinho, sem levar junto os chips — que já
// podem ser clicados enquanto ele chega. O fetch é o MESMO do <Resultado>, e o
// Next deduplica: uma requisição, dois consumidores.
async function FiltroData({ periodo, texto, gratis, dia, href }) {
  const { facetas } = await catalogoEventos(paramsDe({ periodo, texto, gratis, dia }))
  if (!facetas?.dias?.length) return null
  return (
    <Drop rotulo="dia" ativos={dia ? 1 : 0} aberto={Boolean(dia)}>
      <Calendario dias={facetas.dias} selecionado={dia}
                  maxMeses={MESES_NO_CALENDARIO}
                  hrefAlem={href({ dia: '', periodo: 'proximos' })}
                  hrefDia={(d) => href({ dia: dia === d ? '' : d })} />
    </Drop>
  )
}

export default async function Festas({ searchParams }) {
  const sp = await searchParams
  const texto = sp?.texto ?? ''
  const gratis = sp?.gratis === '1'
  // dia escolhido no calendário (querystring é entrada de estranho)
  const dia = /^\d{4}-\d{2}-\d{2}$/.test(sp?.dia ?? '') ? sp.dia : ''
  // Período ESCOLHIDO (chip clicado) vence sempre; o default é que depende da
  // busca (NI-41). Os dois valores andam separados de propósito: o resolvido
  // manda na consulta e no chip aceso, o explícito é o que o formulário
  // propaga — ver SearchForm.
  const periodoUrl = sp?.periodo ?? ''
  const periodo = periodoUrl || periodoPadrao(texto)

  // Preserva os outros filtros ao trocar um deles — sem isso, escolher
  // "grátis" apagaria a busca que a pessoa acabou de digitar.
  const comFiltro = (mudanca) => {
    const q = new URLSearchParams()
    const novo = { periodo, texto, gratis: gratis ? '1' : '', dia, ...mudanca }
    for (const [k, v] of Object.entries(novo)) if (v) q.set(k, v)
    return `/festas?${q}`
  }
  // Clicar um chip de período abandona o dia escolhido: são a mesma pergunta.
  const comPeriodo = (chave) => comFiltro({ periodo: chave, dia: '' })

  return (
    <>
      <div className="secao">
        <h2>festas &amp; shows</h2>
        <Link href="/">← início</Link>
      </div>

      <div className="filtros">
        <SearchForm texto={texto} periodo={periodoUrl} gratis={gratis} dia={dia} />

        <div className="chips" role="group" aria-label="Filtros">
          {PERIODOS.map((p) => (
            <Link key={p.chave} className="chip" href={comPeriodo(p.chave)}
                  data-on={!dia && periodo === p.chave ? '1' : '0'}>
              {p.rotulo}
            </Link>
          ))}
          <span className="chip-sep" aria-hidden="true" />
          <Link className="chip" href={comFiltro({ gratis: gratis ? '' : '1' })}
                data-on={gratis ? '1' : '0'}>
            só grátis
          </Link>
        </div>

        <div className="drops" role="group" aria-label="Filtro por dia">
          {/* fallback com a mesma caixa do <Drop> real: sem ele a barra de
              filtros daria um pulo quando o calendário chegasse */}
          <Suspense fallback={<span className="drop-fantasma">dia ▾</span>}>
            <FiltroData periodo={periodo} texto={texto} gratis={gratis}
                        dia={dia} href={comFiltro} />
          </Suspense>
        </div>
      </div>

      {/* A `key` é o que faz isto funcionar, e é o detalhe não óbvio do NI-50:
          `loading.jsx` só entra quando o SEGMENTO de rota muda, e trocar um
          filtro não muda segmento nenhum — /festas?periodo=hoje e
          /festas?periodo=7d são a mesma rota. Sem a key, o React reusaria a
          fronteira já resolvida e a tela ficaria parada exatamente no gesto
          de que o beta reclamou. Com ela, cada combinação de filtro é uma
          fronteira nova, que suspende e mostra o esqueleto. */}
      <Suspense key={`${periodo}|${texto}|${gratis}|${dia}`}
                fallback={<Esqueleto n={6} />}>
        <Resultado periodo={periodo} texto={texto} gratis={gratis} dia={dia} />
      </Suspense>
    </>
  )
}
