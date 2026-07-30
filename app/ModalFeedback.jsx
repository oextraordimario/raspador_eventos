'use client'

import { useEffect, useState } from 'react'
import posthog from 'posthog-js'
import FormularioFeedback from './FormularioFeedback'

const ERROS = {
  vazio: 'Faltou escrever a mensagem.',
  tipo: 'Escolha um dos assuntos da lista.',
  muitos: 'Chegou muita coisa ao mesmo tempo por aqui. Tente de novo em um minuto.',
  interno: 'Deu erro do nosso lado. Se puder, tente de novo daqui a pouco.',
}

// Overlay client-side por cima da página atual. O <form> por dentro continua
// NATIVO (method="post", action="/api/dados/feedback", sem enctype — logo
// urlencoded) — só interceptamos o submit (evento sobe até esta div: submit
// borbulha no DOM) pra trocar a navegação por uma mensagem dentro do próprio
// modal. A API sempre responde 303 pro fluxo sem JS (ver rota_post em
// api/dados.py); aqui só deixamos o fetch SEGUIR o redirect e lemos os
// parâmetros da URL final (?ok=1 ou ?erro=) — zero mudança no backend. Se o
// fetch falhar (JS quebrado, rede fora), o <form> nativo ainda é o que
// realmente existe no DOM: um clique novo sem o preventDefault cair no
// fallback de sempre, /feedback?ok=1.
export default function ModalFeedback({ aberto, aoFechar, pagina }) {
  const [recebido, setRecebido] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState(null)

  useEffect(() => {
    if (!aberto) return
    setRecebido(false)
    setEnviando(false)
    setErro(null)
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

  async function aoSubmeter(e) {
    e.preventDefault()
    if (enviando) return
    const form = e.target
    setEnviando(true)
    setErro(null)
    try {
      const corpo = new URLSearchParams(new FormData(form))
      const r = await fetch(form.action, { method: 'POST', body: corpo })
      const destino = new URL(r.url)
      if (destino.searchParams.get('ok') === '1') {
        posthog.capture('feedback_submitted',
          { tipo: destino.searchParams.get('tipo') || 'outro' })
        setRecebido(true)
      } else {
        setErro(destino.searchParams.get('erro') || 'interno')
      }
    } catch {
      setErro('interno')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="modal-fundo" onClick={aoFechar}>
      <div className="modal-caixa" role="dialog" aria-modal="true"
           aria-label="Fale com a gente" onClick={(e) => e.stopPropagation()}>
        <div className="modal-cabecalho">
          <h2 className="modal-titulo">fale com a gente</h2>
          <button className="icon-btn modal-fechar" onClick={aoFechar}
                  type="button" aria-label="Fechar">×</button>
        </div>

        {recebido ? (
          <div className="note">
            <strong>Recebido.</strong> Obrigado. Isso vira trabalho de
            verdade por aqui, e se você deixou contato a gente responde.
          </div>
        ) : (
          <div onSubmit={aoSubmeter}>
            {erro && <div className="note erro">{ERROS[erro] ?? ERROS.interno}</div>}
            <FormularioFeedback pagina={pagina} desabilitado={enviando} />
          </div>
        )}
      </div>
    </div>
  )
}
