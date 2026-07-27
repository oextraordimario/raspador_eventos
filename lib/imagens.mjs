// Hosts de imagem liberados — FONTE ÚNICA, lida por dois lugares que precisam
// concordar: o `next.config.mjs` (que autoriza o otimizador) e o `<Flyer>` (que
// decide se tenta renderizar). Se divergissem, host novo viraria imagem
// quebrada na página em vez de card sem foto.
//
// Fonte nova de evento? Acrescente o host aqui e mais nada. Enquanto ele não
// estiver na lista o card degrada para o fallback sem imagem — que é o
// comportamento correto: sem flyer o site funciona, com flyer quebrado não.
// Levantados da base, não deduzidos do nome da plataforma — vários não têm
// nada a ver com o domínio da fonte (o Shotgun serve por Cloudinary, o
// Ingresse por "kraken").
export const HOSTS_IMAGEM = [
  'images.sympla.com.br',                // sympla (426 eventos)
  'assets.bileto.sympla.com.br',         // sympla via bileto
  's3.us-east-1.amazonaws.com',          // ticket and go
  'res.cloudinary.com',                  // shotgun
  'kraken.ingresse.com',                 // ingresse
  'superticket-assets.s3.amazonaws.com', // zig
]

// O Instagram fica de fora de propósito: a URL do CDN dele expira em horas
// (ver CLAUDE.md), então gravar ou servir essa URL entrega imagem morta. Esses
// eventos usam o fallback até termos hospedagem própria da mídia.
export function temFlyer(url) {
  if (!url) return false
  try {
    return HOSTS_IMAGEM.includes(new URL(url).hostname)
  } catch {
    return false
  }
}
