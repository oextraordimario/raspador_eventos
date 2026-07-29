'use client'

import { useState } from 'react'
import Image from 'next/image'
import { temFlyer } from '../../../lib/imagens.mjs'

// Mesma proporção do CSS (.hero) — é o ponto de partida antes de medir a
// imagem de verdade, e também o que sobra fixo pra quadrada/vertical.
const RATIO_PADRAO = 3 / 2

// Flyer grande no topo da página do evento. Usa `contain`, não `cover`:
// flyer de festa carrega informação impressa (line-up, horário, endereço) e
// cortar as bordas jogaria fora justamente o que a pessoa abriu para ver.
//
// A caixa nasce em 3:2 (CSS). Só pra imagem LARGA (mais larga que essa
// proporção) a gente re-mede pela proporção real, assim que ela carrega —
// senão sobra faixa cinza em cima/embaixo. Quadrada/vertical fica como está
// por ora (sobra dos lados; resolve depois).
export function Hero({ src, alto }) {
  const [ratio, setRatio] = useState(null)
  if (!temFlyer(src)) return null

  function aoCarregar(e) {
    const { naturalWidth: w, naturalHeight: h } = e.target
    if (!w || !h) return
    const r = w / h
    if (r > RATIO_PADRAO) setRatio(r)
  }

  return (
    <div className="hero" style={ratio ? { aspectRatio: ratio } : undefined}>
      <Image src={src} alt={`Cartaz de ${alto}`} fill
             sizes="(min-width: 900px) 720px, 100vw" priority
             style={{ objectFit: 'contain' }}
             onLoad={aoCarregar} />
    </div>
  )
}
