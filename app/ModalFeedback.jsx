'use client'

import { useEffect } from 'react'
import { MARCA } from '../lib/config'
import FormularioFeedback from './FormularioFeedback'

// Overlay client-side por cima da página atual. O <form> por dentro continua
// NATIVO (method="post", sem fetch) — abrir em modal muda só ONDE a pessoa
// vê o formulário, não como o envio funciona; submeter ainda navega para
// /feedback?ok=1, que é o fallback de quem clicou sem JS (ver LinkFeedback).
export default function ModalFeedback({ aberto, aoFechar, pagina }) {
  useEffect(() => {
    if (!aberto) return
    const antes = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const naEsc = (e) => { if (e.key === 'Escape') aoFechar() }
    document.addEventListener('keydown', naEsc)
    return () => {
      document.body.style.overflow = antes
      document.removeEventListener('keydown', naEsc)
    }
  }, [aberto, aoFechar])

  if (!aberto) return null

  return (
    <div className="modal-fundo" onClick={aoFechar}>
      <div className="modal-caixa" role="dialog" aria-modal="true"
           aria-label="Falar com a gente" onClick={(e) => e.stopPropagation()}>
        <button className="icon-btn modal-fechar" onClick={aoFechar}
                type="button" aria-label="Fechar">×</button>
        <h2>falar com a gente</h2>
        <p>
          O {MARCA.nome} é feito por uma pessoa só e depende de gente
          contando o que está errado. Preço desatualizado, evento que não
          existe, casa faltando, ideia de melhoria — manda.
        </p>
        <FormularioFeedback pagina={pagina} />
      </div>
    </div>
  )
}
