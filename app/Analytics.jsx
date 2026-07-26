'use client'

import { useEffect } from 'react'

// PostHog — plataforma decidida na spec (§3 passo 3), cobrindo site e MCP numa
// medição só. O critério das Fases 1 e 2 do PRD não é pageview, é "usa de
// verdade": retenção e recorrência.
//
// A ingestão vai pelo PRÓPRIO domínio (/ph/*, rewrite no next.config.mjs).
// Adblocker bloqueia o host do PostHog direto, e o público deste produto é
// justamente o que mais bloqueia — a subcontagem cairia sobre quem a gente
// mais precisa medir. Isso tem que existir desde o primeiro dia: passar a
// proxiar depois invalida a comparação com o histórico.
//
// Sem NEXT_PUBLIC_POSTHOG_KEY o site funciona normalmente e só não mede.
export default function Analytics() {
  const chave = process.env.NEXT_PUBLIC_POSTHOG_KEY

  useEffect(() => {
    if (!chave || typeof window === 'undefined' || window.__ph) return
    window.__ph = true

    // snippet oficial, enxuto: fila de chamadas antes do script carregar
    const ph = (window.posthog = window.posthog || [])
    ph._i = []
    ph.init = function (k, cfg) { ph._i.push([k, cfg]) }
    for (const m of ['capture', 'identify', 'register', 'people']) {
      ph[m] = function () { ph.push([m, arguments]) }
    }

    const s = document.createElement('script')
    s.async = true
    s.src = '/ph/static/array.js'
    s.onload = () => {
      window.posthog.init(chave, {
        api_host: `${location.origin}/ph`,
        // o proxy já esconde o host; sem isso o SDK reescreveria para o
        // domínio do PostHog e o adblocker voltaria a pegar
        ui_host: 'https://us.posthog.com',
        person_profiles: 'identified_only',
        capture_pageview: true,
        capture_pageleave: true,
      })
    }
    document.head.appendChild(s)
  }, [chave])

  return null
}
