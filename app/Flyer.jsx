import Image from 'next/image'
import { temFlyer } from '../lib/imagens.mjs'

// O flyer do evento. Duas responsabilidades, ambas de robustez:
//
// 1. Host desconhecido vira fallback, não imagem quebrada. O otimizador do
//    Next recusa host fora do remotePatterns, e sem esta checagem o card
//    exibiria o ícone de imagem falhada — pior que não ter foto nenhuma.
// 2. Sem imagem, o espaço não fica vazio: entra a inicial do evento, para a
//    lista manter o ritmo visual mesmo com as fontes que não publicam flyer
//    (hoje, o Instagram — URL de CDN que expira em horas).
export default function Flyer({ src, alto, tamanhos, prioridade = false }) {
  if (!temFlyer(src)) {
    return (
      <div className="flyer vazio" aria-hidden="true">
        <span>{(alto || '?').trim().charAt(0).toUpperCase()}</span>
      </div>
    )
  }

  return (
    <div className="flyer">
      <Image
        src={src}
        alt=""            /* decorativo: o nome do evento já está no título ao lado */
        fill
        sizes={tamanhos}
        priority={prioridade}
        unoptimized={false}
      />
    </div>
  )
}

// Versão grande, para o topo da página do evento. Usa `contain`, não `cover`:
// flyer de festa carrega informação impressa (line-up, horário, endereço) e
// cortar as bordas jogaria fora justamente o que a pessoa abriu para ver. O
// fundo preenche a sobra.
export function Hero({ src, alto }) {
  if (!temFlyer(src)) return null
  return (
    <div className="hero">
      <Image src={src} alt={`Cartaz de ${alto}`} fill
             sizes="(min-width: 900px) 720px, 100vw" priority
             style={{ objectFit: 'contain' }} />
    </div>
  )
}
