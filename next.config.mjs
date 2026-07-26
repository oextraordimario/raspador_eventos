/** @type {import('next').NextConfig} */
const config = {
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
