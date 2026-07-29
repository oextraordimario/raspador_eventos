import posthog from 'posthog-js'

const key = process.env.NEXT_PUBLIC_POSTHOG_KEY
const host = process.env.NEXT_PUBLIC_POSTHOG_HOST

// Dev, preview e produção mandam para o MESMO projeto do PostHog — uma key só,
// insights compartilhados. Quem separa é esta propriedade, presente em TODO
// evento: o filtro de contas de teste do projeto marca `ambiente != production`
// como teste, então os números reais não contam a tarde de quem está mexendo no
// site. Na Vercel o valor vem de NEXT_PUBLIC_VERCEL_ENV (production/preview);
// na máquina de quem desenvolve essa variável não existe, e sobra 'development'.
const AMBIENTE = process.env.NEXT_PUBLIC_VERCEL_ENV || 'development'

if (!key) {
  if (process.env.NODE_ENV !== 'production') {
    console.error(
      'NEXT_PUBLIC_POSTHOG_KEY variable required by PostHog is missing or un-configured, ' +
      'this causes events to be silently missed. ' +
      'This error stops appearing once NEXT_PUBLIC_POSTHOG_KEY is configured'
    )
  }
} else {
  posthog.init(key, {
    api_host: '/ph',
    ui_host: host || 'https://us.posthog.com',
    defaults: '2026-01-30',
    capture_exceptions: true,
    person_profiles: 'identified_only',
    capture_pageview: true,
    capture_pageleave: true,
    debug: process.env.NODE_ENV === 'development',

    // A URL vai junto em todo evento capturado, e desde o NI-46 ela pode
    // conter `?perto=<lat>,<lon>` — a coordenada de quem está olhando. Mandar
    // isso a um terceiro contradiz o que a página /sobre promete, e
    // aconteceria em silêncio: ninguém decide capturar a URL, ela vem de
    // graça. Aqui ela é mascarada ANTES de sair do navegador.
    sanitize_properties: (props) => {
      for (const chave of ['$current_url', '$referrer', '$initial_current_url',
                           '$initial_referrer', '$pathname']) {
        if (typeof props[chave] === 'string') {
          props[chave] = props[chave].replace(/([?&]perto=)[^&#]*/g, '$1oculto')
        }
      }
      // Aqui e não em `register()`: super property só existe depois do `loaded`,
      // e o primeiro pageview sai ANTES disso — justamente o evento que mais
      // aparece nos testes locais sairia sem rótulo, contando como produção.
      props.ambiente = AMBIENTE
      return props
    },
  })
}
