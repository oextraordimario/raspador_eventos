import Link from 'next/link'

// Calendário de mês para o filtro de data. Honesto sobre a janela real: a
// grade da fonte cobre ~8 dias (vira na quinta), então só dia com sessão é
// clicável — o resto do mês aparece desabilitado, em vez de fingir que há
// programação. Server component: `hrefDia` chega do pai (server → server
// pode passar função) e devolve a URL com o dia togglado.
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
               'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
const SEMANA = ['s', 't', 'q', 'q', 's', 's', 'd']

// dias: ["YYYY-MM-DD"] com sessão; renderiza cada mês que aparece neles.
export default function Calendario({ dias, selecionado, hrefDia }) {
  const habilitados = new Set(dias)
  const meses = [...new Set(dias.map((d) => d.slice(0, 7)))].sort()

  return (
    <div className="cal">
      {meses.map((mes) => {
        const [ano, m] = mes.split('-').map(Number)
        const nDias = new Date(ano, m, 0).getDate()
        // getDay(): 0=domingo; a grade começa na segunda (padrão BR)
        const coluna1 = (new Date(ano, m - 1, 1).getDay() + 6) % 7
        return (
          <div className="cal-mes" key={mes}>
            <div className="cal-titulo">{MESES[m - 1]} {ano}</div>
            <div className="cal-grade">
              {SEMANA.map((s, i) => (
                <span key={i} className="cal-semana" aria-hidden="true">{s}</span>
              ))}
              {Array.from({ length: coluna1 }, (_, i) => <span key={`v${i}`} />)}
              {Array.from({ length: nDias }, (_, i) => {
                const dia = `${mes}-${String(i + 1).padStart(2, '0')}`
                if (!habilitados.has(dia)) {
                  return <span key={dia} className="cal-dia off">{i + 1}</span>
                }
                return (
                  <Link key={dia} className="cal-dia"
                        href={hrefDia(dia)}
                        data-on={selecionado === dia ? '1' : '0'}
                        aria-label={`Sessões de ${dia}`}>
                    {i + 1}
                  </Link>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
