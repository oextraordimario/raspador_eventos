'use client'

import { useEffect, useRef } from 'react'
import posthog from 'posthog-js'

// O envio acontece no NAVEGADOR, por um form nativo — não há handler de clique
// para instrumentar. O evento é emitido na volta, quando a página chega com
// ?ok=1. Vai só o `tipo`: a mensagem e o contato são o conteúdo do canal e não
// saem da nossa base (§7.6 e §9 da spec). O tipo vem por prop, e não de
// `useSearchParams`, para não exigir uma fronteira de Suspense por um dado que
// a página já tem na mão.
export default function Enviado({ ok, tipo }) {
  const jaFoi = useRef(false)

  useEffect(() => {
    if (!ok || jaFoi.current) return
    jaFoi.current = true   // re-render não pode virar segundo evento
    posthog.capture('feedback_submitted', { tipo: tipo || 'outro' })
  }, [ok, tipo])

  return null
}
