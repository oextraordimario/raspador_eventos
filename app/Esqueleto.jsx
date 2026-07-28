// Esqueleto de carregamento (NI-50).
//
// A queixa do beta — "parece que tá re-puxando da base toda vez que clica um
// filtro" — está tecnicamente certa: filtro é navegação, e navegação é render
// no servidor. O desenho não sai (filtros na URL, SSR sem JS: é o que a Fase 2
// precisa que o buscador leia), então o que muda é o que a pessoa vê enquanto
// espera. Até aqui não havia `loading.jsx` nenhum: a tela ficava parada,
// idêntica, sem sinal de vida — que é o que se lê como "travado".
//
// Isto não deixa nada mais rápido. Muda o que é PERCEBIDO como travado, que é
// literalmente o que foi reclamado.

export function LinhaCard({ cartaz = false }) {
  return (
    <div className={`card sk-card${cartaz ? ' fcard' : ''}`} aria-hidden="true">
      <div className={`${cartaz ? 'cartaz' : 'flyer'} sk`} />
      <div className="body">
        <div className="sk sk-linha" style={{ width: '72%', height: 17 }} />
        <div className="sk sk-linha" style={{ width: '45%', height: 13 }} />
        <div className="sk sk-linha" style={{ width: '90%', height: 12 }} />
        <div className="sk sk-linha" style={{ width: '30%', height: 13 }} />
      </div>
    </div>
  )
}

// `n` acompanha o que a rota costuma mostrar acima da dobra: mais que isso é
// esqueleto que ninguém vê, e menos deixa a página pulando quando o dado chega.
export default function Esqueleto({ n = 6, cartaz = false }) {
  return (
    <>
      <p className="count sk-texto">carregando…</p>
      <div className="list">
        {Array.from({ length: n }, (_, i) => (
          <LinhaCard key={i} cartaz={cartaz} />
        ))}
      </div>
    </>
  )
}
