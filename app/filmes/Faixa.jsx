'use client'

import { useRef } from 'react'
import Link from 'next/link'
import Cartaz from './Cartaz'

// Uma faixa da vitrine (estilo streaming): título + trilho horizontal de
// pôsteres. No dedo o scroll é nativo; no mouse não existe gesto horizontal
// (e a scrollbar fica escondida por design), então as setas são o caminho —
// por isso o componente é client. Elas rolam ~80% da largura visível.
export default function Faixa({ titulo, filmes, prioridade = false }) {
  const trilho = useRef(null)
  const rolar = (dir) => trilho.current?.scrollBy(
    { left: dir * trilho.current.clientWidth * 0.8, behavior: 'smooth' })

  return (
    <section className="faixa">
      <div className="faixa-topo">
        <h2 className="faixa-titulo">{titulo}</h2>
        <div className="faixa-setas">
          <button type="button" className="icon-btn" aria-label={`Rolar ${titulo} para trás`}
                  onClick={() => rolar(-1)}>‹</button>
          <button type="button" className="icon-btn" aria-label={`Rolar ${titulo} para frente`}
                  onClick={() => rolar(1)}>›</button>
        </div>
      </div>
      <div className="trilho" ref={trilho}>
        {filmes.map((f, i) => (
          <Link key={f.id} className="fposter" href={`/filmes/${f.id}`}>
            {/* `poster_proprio` PRIMEIRO, como no FilmCard e na página do
                filme: é a cópia no nosso storage (NI-37), e o hotlink do CDN
                da fonte é só o fallback de enquanto a cópia não existe. Este
                era o único dos três lugares que renderizava pôster e não fazia
                isso — as 55 imagens da vitrine saíam todas do CDN da
                Ingresso.com, com a nossa cópia dos 30 pôsteres parada no Blob.
                Uma delas ("Xica da Silva") não renderizava por causa disso. */}
            <Cartaz src={f.poster_proprio || f.poster} titulo={f.titulo}
                    tamanhos="150px" prioridade={prioridade && i < 4} />
            <span className="fposter-titulo">{f.titulo}</span>
            <span className="fposter-meta">
              {f.em_pre_venda === 1 ? 'pré-venda' : (f.generos || '').split(',')[0]}
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}
