'use client'

import { useEffect, useRef } from 'react'

// Um filtro sempre visível que abre em dropdown sobre <details>/<summary>:
// as opções são <Link> que togglam o valor na URL, então cada clique
// re-renderiza a página; `aberto` deixa o dropdown já aberto quando o grupo
// tem seleção, para a multi-escolha não exigir reabrir a cada clique.
// A camada de JS só coordena o fechamento: clique fora fecha, e abrir um
// Drop fecha os irmãos (sem JS o <details> segue funcionando, só não fecha
// sozinho).
export default function Drop({ rotulo, ativos = 0, aberto = false, classeMenu = '', children }) {
  const ref = useRef(null)

  useEffect(() => {
    function aoClicarFora(e) {
      const el = ref.current
      if (el?.open && !el.contains(e.target)) el.open = false
    }
    document.addEventListener('click', aoClicarFora)
    return () => document.removeEventListener('click', aoClicarFora)
  }, [])

  function aoAbrir(e) {
    if (!e.currentTarget.open) return
    document.querySelectorAll('details.drop[open]').forEach((outro) => {
      if (outro !== e.currentTarget) outro.open = false
    })
  }

  return (
    <details className="drop" open={aberto || undefined} ref={ref} onToggle={aoAbrir}>
      <summary>
        {rotulo}
        {ativos > 0 && <span className="drop-n">{ativos}</span>}
        <span className="drop-caret" aria-hidden="true">▾</span>
      </summary>
      <div className={classeMenu ? `drop-menu ${classeMenu}` : 'drop-menu'}>{children}</div>
    </details>
  )
}
