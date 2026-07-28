import { Suspense } from 'react'
import Link from 'next/link'
import { catalogoEventos, procedencia, idParaSlug } from '../../lib/api'
import Esqueleto from '../Esqueleto'
import { agruparPorDia, rotuloDia, diaMes, horaOuNada, reais, tituloLimpo } from '../../lib/formato'
import { MARCA, PERIODOS, TIPOS, periodoPadrao } from '../../lib/config'
import { colecoesAgora } from '../../lib/colecoes'
import Procedencia from '../Procedencia'
import SearchForm from '../SearchForm'
import Flyer from '../Flyer'
import Drop from '../Drop'
import DropFiltro from '../DropFiltro'
import Calendario from '../Calendario'

// Um dia escolhido no calendário vira a janela daquele dia LOCAL (Brasília é
// -03 fixo) e SUBSTITUI o atalho de período — os dois respondem à mesma
// pergunta, e deixar os dois valendo produziria interseções vazias sem que a
// pessoa entendesse por quê.
function paramsDe({ periodo, texto, gratis, dia, bairros, tipo }) {
  const p = { texto, gratis: gratis ? '1' : '', tipo,
              bairro: bairros?.join(',') ?? '' }
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
async function Resultado({ filtros }) {
  const { texto, periodo } = filtros
  const [{ eventos }, fontes] = await Promise.all([
    catalogoEventos(paramsDe(filtros)),
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
              : 'Tente ampliar o período ou tirar um dos filtros.'}
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

// Fração mínima da agenda que precisa estar classificada para os chips de
// tipo aparecerem (NI-44). Não é preciosismo: a busca esconde o sem-rótulo de
// ninguém — `tipo=festa` traz também os NULL, porque errar para o lado de
// esconder festa real é o pior erro possível aqui —, e com 3 de 4 eventos sem
// rótulo o chip devolveria a lista inteira. Um filtro que promete um recorte
// e entrega tudo é pior que filtro nenhum.
//
// O gate é sobre o DADO, não sobre a UI: quando o NI-05 (LLM) assumir a
// coluna, a cobertura sobe e os chips aparecem sozinhos. Medição de
// 2026-07-28: 24% (91 de 379) — abaixo do piso, então eles não aparecem
// ainda. O parâmetro `tipo` já existe na API e no MCP.
const COBERTURA_TIPO = 0.5

function mostrarTipos(tipos) {
  if (!tipos) return false
  const total = tipos.festa + tipos.show + tipos.sem_rotulo
  return total > 0 && (tipos.festa + tipos.show) / total >= COBERTURA_TIPO
}

// O calendário é o único filtro que depende da base (precisa saber que dias
// têm evento), então ele suspende sozinho, sem levar junto os chips — que já
// podem ser clicados enquanto ele chega. O fetch é o MESMO do <Resultado>, e o
// Next deduplica: uma requisição, dois consumidores.
async function FiltrosDaBase({ filtros, href, estado }) {
  const { facetas } = await catalogoEventos(paramsDe(filtros))
  const { dia, bairros, tipo } = filtros
  return (
    <>
      {mostrarTipos(facetas?.tipos) && TIPOS.map((t) => (
        <Link key={t.chave} className="chip"
              href={href({ tipo: tipo === t.chave ? '' : t.chave })}
              data-on={tipo === t.chave ? '1' : '0'}>
          {t.rotulo}
        </Link>
      ))}
      {facetas?.dias?.length > 0 && (
        <Drop rotulo="dia" ativos={dia ? 1 : 0} aberto={Boolean(dia)}>
          <Calendario dias={facetas.dias} selecionado={dia}
                      maxMeses={MESES_NO_CALENDARIO}
                      hrefAlem={href({ dia: '', periodo: 'proximos' })}
                      hrefDia={(d) => href({ dia: dia === d ? '' : d })} />
        </Drop>
      )}
      {facetas?.bairros?.length > 0 && (
        <DropFiltro rotulo="bairro" base="/festas" estado={estado}
                    param="bairro" selecionados={bairros}
                    opcoes={facetas.bairros.map((b) => ({ valor: b, rotulo: b }))} />
      )}
    </>
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
  const bairros = (sp?.bairro ?? '').split(',').filter(Boolean)
  const tipo = TIPOS.some((t) => t.chave === sp?.tipo) ? sp.tipo : ''

  const filtros = { periodo, texto, gratis, dia, bairros, tipo }

  // Preserva os outros filtros ao trocar um deles — sem isso, escolher
  // "grátis" apagaria a busca que a pessoa acabou de digitar.
  const comFiltro = (mudanca) => {
    const q = new URLSearchParams()
    const novo = { periodo, texto, gratis: gratis ? '1' : '', dia, tipo,
                   bairro: bairros.join(','), ...mudanca }
    for (const [k, v] of Object.entries(novo)) if (v) q.set(k, v)
    return `/festas?${q}`
  }
  // Clicar um chip de período abandona o dia escolhido: são a mesma pergunta.
  const comPeriodo = (chave) => comFiltro({ periodo: chave, dia: '' })
  // O DropFiltro é client component: recebe o estado como strings e monta a
  // URL do "aplicar" sozinho, sem useSearchParams (que exigiria Suspense).
  const estado = { periodo, texto, gratis: gratis ? '1' : '', dia, tipo,
                   bairro: bairros.join(',') }
  const colecoes = colecoesAgora()

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

          {/* Coleções da época (NI-47): o chip só existe dentro da janela do
              ano e apenas preenche a busca — é atalho, não filtro novo. Por
              isso ele também abre a janela de período: quem procura arraiá
              quer os de agosto, não os de hoje. */}
          {colecoes.map((c) => (
            <Link key={c.chave} className="chip chip-colecao"
                  href={texto === c.termos
                    ? comFiltro({ texto: '', periodo: '' })
                    : comFiltro({ texto: c.termos, periodo: 'proximos', dia: '' })}
                  data-on={texto === c.termos ? '1' : '0'}>
              {c.rotulo}
            </Link>
          ))}
        </div>

        <div className="drops" role="group" aria-label="Filtros de dia e bairro">
          {/* fallback com a mesma caixa dos <Drop> reais: sem ele a barra de
              filtros daria um pulo quando eles chegassem */}
          <Suspense fallback={
            <>
              <span className="drop-fantasma">dia ▾</span>
              <span className="drop-fantasma">bairro ▾</span>
            </>
          }>
            <FiltrosDaBase filtros={filtros} href={comFiltro} estado={estado} />
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
      <Suspense key={JSON.stringify(filtros)} fallback={<Esqueleto n={6} />}>
        <Resultado filtros={filtros} />
      </Suspense>
    </>
  )
}
