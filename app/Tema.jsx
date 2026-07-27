'use client'

import { useEffect, useState } from 'react'

const SOL = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4" />
  </svg>
)

const LUA = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
  </svg>
)

// A barra do navegador no celular acompanha o fundo de cada tema. Vive aqui
// (e não no viewport do layout) porque o tema muda no cliente, por clique.
const COR_BARRA = { light: '#eef0f2', dark: '#0f1311' }

function aplicar(tema) {
  document.documentElement.setAttribute('data-theme', tema)
  document.querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', COR_BARRA[tema])
}

export default function Tema() {
  const [tema, setTema] = useState(null)

  // Light é o padrão para todo mundo — o site NÃO segue a preferência do
  // sistema. Quem quiser dark escolhe no botão, e a escolha fica no
  // localStorage. Só depois de montar: no servidor não existe localStorage,
  // e assumir um valor causaria troca visível de tema no primeiro paint.
  useEffect(() => {
    const atual = localStorage.getItem('tema') || 'light'
    setTema(atual)
    aplicar(atual)
  }, [])

  function alternar() {
    const novo = tema === 'dark' ? 'light' : 'dark'
    setTema(novo)
    localStorage.setItem('tema', novo)
    aplicar(novo)
  }

  return (
    <button className="icon-btn" onClick={alternar} type="button"
            aria-label="Alternar tema claro e escuro" title="Alternar tema">
      {/* mostra o destino do clique, não o estado atual */}
      {tema === 'light' ? LUA : SOL}
    </button>
  )
}
