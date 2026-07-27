import { HOSTS_IMAGEM } from './lib/imagens.mjs'

/** @type {import('next').NextConfig} */
const config = {
  // O flyer passa pelo otimizador do Next, e não por <img> direto, porque o
  // original é pesado demais para uma lista: a imagem do Sympla vem em PNG de
  // ~650 KB e a fonte não publica variante menor (testado: só existe o -lg).
  // Quarenta cards seriam ~26 MB no celular — exatamente o público que este
  // site precisa atender bem. Otimizado, cada um vira alguns KB em webp.
  images: {
    remotePatterns: HOSTS_IMAGEM.map((hostname) => ({ protocol: 'https', hostname })),
    // Larguras que a lista e a página de evento realmente pedem. Enxugar isso
    // importa: cada largura gerada conta na cota de otimização do plano Hobby.
    imageSizes: [80, 128, 160, 256],
    deviceSizes: [640, 828, 1080],
    minimumCacheTTL: 2678400, // 31 dias — o flyer não muda depois de publicado
  },

  async rewrites() {
    return [
      // Ingestão do PostHog pelo próprio domínio. Adblocker bloqueia o host
      // do PostHog direto; servir por aqui evita a subcontagem justamente do
      // público deste produto (jovem, mobile, muito adblock). Precisa existir
      // DESDE O INÍCIO — retrofitar depois invalida a série histórica.
      { source: '/ph/static/:path*', destination: 'https://us-assets.i.posthog.com/static/:path*' },
      { source: '/ph/array/:path*', destination: 'https://us-assets.i.posthog.com/array/:path*' },
      { source: '/ph/:path*', destination: 'https://us.i.posthog.com/:path*' },
    ]
  },
  skipTrailingSlashRedirect: true,
}
export default config
