'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

// O rodapé é global e o formulário quer saber DE ONDE a pessoa clicou — é a
// diferença entre "o site tem um bug" e "a página do evento X tem um bug".
// `usePathname` roda no SSR também, então o href já sai correto no HTML: o
// canal continua funcionando sem JS, e o campo `pagina` deixa de nascer vazio.
export default function LinkFeedback({ children }) {
  const aqui = usePathname()
  const href = aqui && aqui !== '/feedback'
    ? `/feedback?de=${encodeURIComponent(aqui)}`
    : '/feedback'
  return <Link href={href}>{children}</Link>
}
