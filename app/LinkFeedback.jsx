'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

// O rodapé é global e o formulário quer saber DE ONDE a pessoa clicou — é a
// diferença entre "o site tem um bug" e "a página do evento X tem um bug".
// `usePathname` roda no SSR também, então o href já sai correto no HTML: o
// canal continua funcionando sem JS, e o campo `pagina` deixa de nascer vazio.
export default function LinkFeedback() {
  const aqui = usePathname()
  const href = aqui && aqui !== '/feedback'
    ? `/feedback?de=${encodeURIComponent(aqui)}`
    : '/feedback'
  return (
    <Link href={href} className="fab-feedback" aria-label="Reportar um bug"
          title="Reportar um bug">
      <svg width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8 2l1.88 1.88M14.12 3.88L16 2" />
        <path d="M9 7.13v-1a3 3 0 1 1 6 0v1" />
        <path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6z" />
        <path d="M12 20v-9M6.53 9C4.6 8.8 3 7.1 3 5M6 13H2M6.53 17c-1.93.2-3.53 1.9-3.53 4" />
        <path d="M17.47 9c1.93-.2 3.53-1.9 3.53-4M18 13h4M17.47 17c1.93.2 3.53 1.9 3.53 4" />
      </svg>
    </Link>
  )
}
