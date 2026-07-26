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

export default function Tema() {
  const [tema, setTema] = useState(null)

  // Só depois de montar: no servidor não existe preferência de sistema nem
  // localStorage, e assumir uma delas causaria troca visível de tema no
  // primeiro paint.
  useEffect(() => {
    const salvo = localStorage.getItem('tema')
    const atual = salvo ||
      (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
    setTema(atual)
    document.documentElement.setAttribute('data-theme', atual)
  }, [])

  function alternar() {
    const novo = tema === 'dark' ? 'light' : 'dark'
    setTema(novo)
    localStorage.setItem('tema', novo)
    document.documentElement.setAttribute('data-theme', novo)
  }

  return (
    <button className="icon-btn" onClick={alternar} type="button"
            aria-label="Alternar tema claro e escuro" title="Alternar tema">
      {/* mostra o destino do clique, não o estado atual */}
      {tema === 'light' ? LUA : SOL}
    </button>
  )
}
