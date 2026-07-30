'use client'

import { useState } from 'react'
import Image from 'next/image'
import { temFlyer } from '../../../lib/imagens.mjs'
import { diaSemana, diaMes, reais } from '../../../lib/formato'
import { TicketCta } from './CtaButton'
import { MapaEmbed, AgendaLink, Compartilhar } from './Acoes'

// Até aqui (quadrada ou vertical) a capa vira coluna esquerda; acima disso
// (paisagem) ela continua no topo, largura plena — ver `.doc-corpo--estreita`
// no globals.css.
const LIMIAR_ESTREITA = 1.05

// O corpo inteiro da página do evento é UM componente client (não só o mapa
// e os botões) porque o layout depende da proporção REAL da capa, que só se
// conhece depois que a imagem carrega — client component é o que permite
// medir e reagir. A capa usa `contain`, não `cover`: flyer de festa carrega
// informação impressa (line-up, horário, endereço) e cortar as bordas
// jogaria fora justamente o que a pessoa abriu para ver.
export function Corpo({ ev, titulo, horario, pagina }) {
  const [ratio, setRatio] = useState(null)
  const estreita = ratio != null && ratio <= LIMIAR_ESTREITA

  function aoCarregar(e) {
    const { naturalWidth: w, naturalHeight: h } = e.target
    if (w && h) setRatio(w / h)
  }

  return (
    <div className={`doc-corpo${estreita ? ' doc-corpo--estreita' : ''}`}>
      {/* `.col-imagem` é quem ocupa a área do grid (em ambos os layouts); o
          `.hero` sticky, dentro dela, só sabe até onde "descer" porque o pai
          tem altura de verdade (`align-self: stretch` no estreito) — sticky
          direto no item que abrange 2 linhas do grid NÃO se limita à área
          (o item não fica esticado por padrão) e a imagem invadia o mapa. */}
      {temFlyer(ev.imagem) && (
        <div className="col-imagem">
          <div className="hero" style={ratio ? { aspectRatio: ratio } : undefined}>
            <Image src={ev.imagem} alt={`Cartaz de ${titulo}`} fill
                   sizes="(min-width: 900px) 720px, 100vw" priority
                   style={{ objectFit: 'contain' }}
                   onLoad={aoCarregar} />
          </div>
        </div>
      )}

      <div className="col-info">
        <h1>{titulo}</h1>
        <div className="when">
          {diaSemana(ev.start_date)} {diaMes(ev.start_date)}
          {horario && ` · ${horario}`}
        </div>
        <div className="where">
          {ev.local_nome || 'local a confirmar'}
          {ev.bairro && ` · ${ev.bairro}`}
          {ev.endereco && <><br /><span className="also">{ev.endereco}</span></>}
        </div>

        {ev.descricao && (
          <div className="sec-sobre">
            <div className="label">sobre</div>
            <div className="desc">{ev.descricao}</div>
            {ev.descricao_truncada && (
              <div className="desc-corte">
                Texto do organizador, em trecho. O resto está na página da fonte.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Mesma lógica do `.col-imagem`: `.col-acoes` é o item do grid (área
          "acoes", esticada no layout largo — ela abrange as linhas de
          `.col-info` e do mapa), e o sticky fica no `.col-acoes-corpo` de
          dentro, que é quem de fato sabe até onde descer. */}
      <div className="col-acoes">
        <div className="col-acoes-corpo">
          {ev.lotes?.length > 0 && (
            <div className="sec-ingressos">
              <div className="label">ingressos</div>
              <div className="box">
                {ev.lotes.map((lo, i) => (
                  <div className="row" key={i}>
                    {/* o nome do lote fica CRU, como a fonte publica: a condição
                        ("CORTESIA FEMININA ATÉ 00H") mora nele, de propósito */}
                    <div className="row-name">{lo.nome}</div>
                    <div className={`row-val${lo.gratis ? ' free' : ''}`}>
                      {lo.gratis ? 'grátis' : reais(lo.preco)}
                      {!lo.gratis && lo.taxa > 0 && (
                        <small>inclui {reais(lo.taxa)} de taxa</small>
                      )}
                      {lo.esgotado === 1 && <small>esgotado</small>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <TicketCta href={ev.url} fonte={ev.fonte} haPrice={ev.preco_min != null} />

          <div className="acoes">
            <AgendaLink ev={ev} titulo={titulo} url={pagina} />
            <Compartilhar titulo={titulo} url={pagina} />
          </div>
        </div>
      </div>

      <MapaEmbed ev={ev} />
    </div>
  )
}
