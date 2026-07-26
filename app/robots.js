import { ORIGEM } from '../lib/config'

export default function robots() {
  return {
    rules: [
      // Aberto de propósito: a Fase 2 depende de o buscador e o agente
      // conseguirem ler. A rota /ph/ é só o proxy de ingestão do PostHog —
      // não é conteúdo e não deve ser rastreada.
      { userAgent: '*', allow: '/', disallow: ['/ph/'] },
    ],
    sitemap: `${ORIGEM}/sitemap.xml`,
  }
}
