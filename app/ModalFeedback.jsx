'use client'

import { useEffect } from 'react'
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
           aria-label="Fale com a gente" onClick={(e) => e.stopPropagation()}>
        <div className="modal-cabecalho">
          <h2 className="modal-titulo">fale com a gente</h2>
          <button className="icon-btn modal-fechar" onClick={aoFechar}
                  type="button" aria-label="Fechar">×</button>
        </div>
        <FormularioFeedback pagina={pagina} />
      </div>
    </div>
  )
}
