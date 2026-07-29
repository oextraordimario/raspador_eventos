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

  async redirects() {
    // /filmes virou /cinema. O site já está aberto ao público (sitemap e
    // llms.txt indexados) — link salvo, resultado de busca ou o llms.txt de
    // um agente ainda desatualizado não pode virar 404.
    return [
      { source: '/filmes', destination: '/cinema', permanent: true },
      { source: '/filmes/:id', destination: '/cinema/:id', permanent: true },
    ]
  },

  async rewrites() {
    // Em produção quem roteia /api/dados/* para a função Python é o
    // vercel.json, e o Next nunca vê essas URLs. Em desenvolvimento a API roda
    // num processo à parte (`python api/dados.py 8000`), e até agora só o SSR
    // falava com ela — pelo API_INTERNA, do lado do servidor. O formulário de
    // feedback mudou isso: ele é um <form> nativo, então quem faz o POST é o
    // NAVEGADOR, na origem do site. Sem esta rewrite o envio bateria em 404 na
    // 1007 e o canal só seria testável depois de deployado.
    const dev = process.env.API_INTERNA
      ? [{ source: '/api/dados/:rota*', destination: `${process.env.API_INTERNA}/:rota*` }]
      : []
    return [
      ...dev,
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
