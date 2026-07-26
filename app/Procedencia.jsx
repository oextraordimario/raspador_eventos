import { diaMes, hora } from '../lib/formato'

// A idade do dado é informação que o usuário precisa ver, não detalhe interno.
// Enquanto a raspagem não for comprovadamente diária, esconder que o catálogo
// é de três dias atrás é o pior modo de falha deste produto: resposta errada
// com cara de resposta certa. Com o cron estável, isto vira rodapé discreto —
// que é exatamente o que já é aqui.
export default function Procedencia({ fontes }) {
  if (!fontes?.length) return null

  const agora = Date.now()
  const idade = (iso) => Math.floor((agora - new Date(iso).getTime()) / 864e5)
  const maisVelha = Math.max(...fontes.map((f) => idade(f.ultima_coleta)))

  return (
    <details className="proc">
      <summary>
        <span className={`fresh-btn${maisVelha <= 1 ? ' ok' : ''}`}>
          {maisVelha <= 0 ? 'atualizado hoje' : `atualizado há ${maisVelha}d`}
        </span>
      </summary>
      <div className="box" style={{ marginTop: 10 }}>
        {fontes.map((f) => {
          const d = idade(f.ultima_coleta)
          return (
            <div className="row" key={f.fonte}>
              <div className="row-name">
                {f.fonte}
                <span className="also">  {f.futuros} eventos futuros</span>
              </div>
              <div className={`row-val when-col${d > 1 ? ' bad' : ''}`}>
                {diaMes(f.ultima_coleta)} {hora(f.ultima_coleta)} ({d}d)
              </div>
            </div>
          )
        })}
      </div>
    </details>
  )
}
