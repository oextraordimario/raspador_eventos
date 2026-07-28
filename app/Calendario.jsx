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
//
// `maxMeses` e `hrefAlem` entraram com o calendário de EVENTOS (NI-43): a
// grade de cinema cobre ~8 dias e cabe inteira, mas a agenda de festas alcança
// meses, e empilhar seis blocos de mês dentro de um dropdown é uma lista de
// rolagem, não um calendário. Com o limite, os meses além dele viram uma linha
// só, que leva ao período aberto — a informação de que existe mais não se
// perde, e o dropdown continua sendo um calendário. Sem `maxMeses` (o caso do
// cinema), nada muda.
export default function Calendario({ dias, selecionado, hrefDia,
                                     maxMeses = 0, hrefAlem }) {
  const habilitados = new Set(dias)
  const todos = [...new Set(dias.map((d) => d.slice(0, 7)))].sort()
  const meses = maxMeses > 0 ? todos.slice(0, maxMeses) : todos
  const alem = maxMeses > 0
    ? dias.filter((d) => d.slice(0, 7) > meses.at(-1)).length
    : 0

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

      {alem > 0 && hrefAlem && (
        <Link className="cal-alem" href={hrefAlem}>
          + {alem} {alem === 1 ? 'dia' : 'dias'} depois de{' '}
          {MESES[Number(meses.at(-1).slice(5)) - 1]}
        </Link>
      )}
    </div>
  )
}
