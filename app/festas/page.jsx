import Link from 'next/link'
import { listarEventos, procedencia, idParaSlug } from '../../lib/api'
import { agruparPorDia, rotuloDia, diaMes, horaOuNada, reais, tituloLimpo } from '../../lib/formato'
import { MARCA, PERIODOS, periodoPadrao } from '../../lib/config'
import Procedencia from '../Procedencia'
import SearchForm from '../SearchForm'
import Flyer from '../Flyer'

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

export default async function Festas({ searchParams }) {
  const sp = await searchParams
  const texto = sp?.texto ?? ''
  const gratis = sp?.gratis === '1'
  // Período ESCOLHIDO (chip clicado) vence sempre; o default é que depende da
  // busca (NI-41). Os dois valores andam separados de propósito: o resolvido
  // manda na consulta e no chip aceso, o explícito é o que o formulário
  // propaga — ver SearchForm.
  const periodoUrl = sp?.periodo ?? ''
  const periodo = periodoUrl || periodoPadrao(texto)

  const [eventos, fontes] = await Promise.all([
    listarEventos({ periodo, texto, gratis: gratis ? '1' : '' }),
    procedencia(),
  ])
  const grupos = agruparPorDia(eventos)

  // Preserva os outros filtros ao trocar um deles — sem isso, escolher
  // "grátis" apagaria a busca que a pessoa acabou de digitar.
  const comFiltro = (mudanca) => {
    const q = new URLSearchParams()
    const novo = { periodo, texto, gratis: gratis ? '1' : '', ...mudanca }
    for (const [k, v] of Object.entries(novo)) if (v) q.set(k, v)
    return `/festas?${q}`
  }

  return (
    <>
      <div className="secao">
        <h2>festas &amp; shows</h2>
        <Link href="/">← início</Link>
      </div>

      <div className="filtros">
        <SearchForm texto={texto} periodo={periodoUrl} gratis={gratis} />

        <div className="chips" role="group" aria-label="Filtros">
          {PERIODOS.map((p) => (
            <Link key={p.chave} className="chip" href={comFiltro({ periodo: p.chave })}
                  data-on={periodo === p.chave ? '1' : '0'}>
              {p.rotulo}
            </Link>
          ))}
          <span className="chip-sep" aria-hidden="true" />
          <Link className="chip" href={comFiltro({ gratis: gratis ? '' : '1' })}
                data-on={gratis ? '1' : '0'}>
            só grátis
          </Link>
        </div>
      </div>

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
