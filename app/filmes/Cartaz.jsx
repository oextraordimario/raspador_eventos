import Image from 'next/image'
import { temFlyer } from '../../lib/imagens.mjs'

// O pôster do filme (retrato 2:3, como a fonte publica). Mesmas duas
// responsabilidades do <Flyer> dos eventos: host fora da lista vira fallback
// (não imagem quebrada), e sem pôster entra a inicial do título para a
// vitrine manter o ritmo. Hoje a URL é o CDN da Ingresso.com (hotlink) —
// fallback declarado na spec até o storage próprio do NI-37.
export default function Cartaz({ src, titulo, tamanhos, prioridade = false }) {
  if (!temFlyer(src)) {
    return (
      <div className="cartaz vazio" aria-hidden="true">
        <span>{(titulo || '?').trim().charAt(0).toUpperCase()}</span>
      </div>
    )
  }
  return (
    <div className="cartaz">
      <Image src={src} alt="" fill sizes={tamanhos} priority={prioridade} />
    </div>
  )
}
