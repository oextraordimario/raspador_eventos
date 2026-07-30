'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import posthog from 'posthog-js'

// "Perto de mim" (NI-46). O único filtro do site que NÃO nasce na URL por um
// clique de link: a coordenada só existe depois de a pessoa autorizar o
// navegador. Depois disso ele vira `?perto=`, como todos os outros — o
// endereço continua compartilhável e o SSR continua entregando a página
// pronta.
//
// POSTURA, e ela é a razão de este arquivo ter tantos comentários: a
// coordenada de quem está olhando é o dado mais sensível que este site toca.
// Ela desce como parâmetro, é usada na ordenação da query e não é gravada em
// lugar nenhum — nem na base, nem em log. E não vai para o analytics: o
// PostHog captura a URL de cada pageview, então `?perto=` iria junto, para um
// TERCEIRO, sem ninguém ter decidido isso. Quem impede é o `before_send` do
// instrumentation-client.js — se este botão for removido um dia, aquela máscara
// pode ir junto.
// `estado` são os params atuais da URL como STRINGS, e a URL é montada aqui —
// mesmo contrato do DropFiltro. Uma função `href` como prop seria mais direta,
// mas função não atravessa a fronteira server → client: o React descarta o
// componente inteiro, e a página renderiza sem o botão, sem erro visível.
export default function PertoDeMim({ ativo, base, estado: params }) {
  const router = useRouter()
  const [estado, setEstado] = useState('') // '' | 'pedindo' | 'negado'

  function url(coordenada) {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries({ ...params, perto: coordenada })) {
      if (v) q.set(k, v)
    }
    const qs = q.toString()
    return qs ? `${base}?${qs}` : base
  }

  function clicar() {
    if (ativo) {
      router.push(url(''))   // desligar não pede permissão nenhuma
      return
    }
    if (!navigator.geolocation) {
      setEstado('negado')
      return
    }
    setEstado('pedindo')
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords
        // 4 casas ≈ 11 m: mais que suficiente para ordenar bares, e menos
        // preciso que a leitura crua do aparelho
        posthog.capture('nearby_used', { granted: true })  // NUNCA a coordenada
        // volta ao estado neutro ANTES de navegar: a navegação é
        // client-side e este componente não remonta, então um 'pedindo'
        // esquecido deixaria o botão travado em "localizando…" para sempre
        setEstado('')
        router.push(url(`${latitude.toFixed(4)},${longitude.toFixed(4)}`))
      },
      () => {
        setEstado('negado')
        posthog.capture('nearby_used', { granted: false })
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    )
  }

  return (
    <>
      <button type="button" className="chip" onClick={clicar}
              data-on={ativo ? '1' : '0'} disabled={estado === 'pedindo'}>
        {estado === 'pedindo' ? 'localizando…' : 'perto de mim'}
      </button>
      {estado === 'negado' && (
        <span className="chip-aviso">
          sem acesso à localização, o filtro de bairro resolve
        </span>
      )}
    </>
  )
}
