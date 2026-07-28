'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Drop from './Drop'

// Grupo de filtro em dropdown com checkboxes e botão "aplicar": a seleção é
// local e só vira navegação (uma só) no aplicar — diferente dos chips-link
// antigos, que navegavam a cada clique. `estado` traz os params atuais da URL
// como strings (o server component já os tem; evita useSearchParams, que
// exigiria Suspense) e `limpa` zera o param mutuamente exclusivo (rede ↔
// cinema). `unico` faz o grupo se comportar como escolha única (horário).
export default function DropFiltro({ rotulo, base, estado, param, opcoes,
                                     selecionados = [], unico = false, limpa }) {
  const router = useRouter()
  const [marcados, setMarcados] = useState(selecionados)

  // navegou (aplicou, limpou, voltou): re-ancora a seleção no que a URL diz
  const naUrl = selecionados.join(',')
  useEffect(() => { setMarcados(naUrl.split(',').filter(Boolean)) }, [naUrl])

  const alternar = (valor) => setMarcados((prev) =>
    prev.includes(valor) ? prev.filter((v) => v !== valor)
      : unico ? [valor] : [...prev, valor])

  const aplicar = (e) => {
    const novo = { ...estado, [param]: marcados.join(',') }
    if (limpa) novo[limpa] = ''
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(novo)) if (v) q.set(k, v)
    const qs = q.toString()
    e.currentTarget.closest('details')?.removeAttribute('open')
    router.push(qs ? `${base}?${qs}` : base)
  }

  return (
    <Drop rotulo={rotulo} ativos={selecionados.length} classeMenu="drop-menu-lista">
      <div className="drop-opcoes">
        {opcoes.map((o) => (
          <label key={o.valor} className="drop-opcao">
            <input type="checkbox" checked={marcados.includes(o.valor)}
                   onChange={() => alternar(o.valor)} />
            {o.rotulo}
          </label>
        ))}
      </div>
      <button type="button" className="drop-aplicar" onClick={aplicar}>aplicar</button>
    </Drop>
  )
}
