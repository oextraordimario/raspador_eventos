import Link from 'next/link'

// Calendário de mês para o filtro de data. Honesto sobre a janela real: a
// grade da fonte cobre ~8 dias (vira na quinta), então só dia com sessão é
// clicável — o resto do mês aparece desabilitado, em vez de fingir que há
// programação. Server component: `hrefDia`/`hrefMes` chegam do pai (server →
// server pode passar função) e devolvem a URL com o dia ou o mês togglado.
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
               'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
const SEMANA = ['s', 't', 'q', 'q', 's', 's', 'd']

// dias: ["YYYY-MM-DD"] com sessão; renderiza cada mês que aparece neles.
//
// `maxMeses` mostra só um recorte de cada vez — a grade de cinema cobre ~8
// dias e cabe inteira (maxMeses=0, todos os meses, sem setas), mas a agenda
// de festas alcança meses, e empilhar todos seria rolagem, não calendário.
// Com o recorte, as setas laterais (`hrefMes`) andam um mês por clique sem
// esconder o resto do acervo: quem procura o aniversário daqui a três meses
// navega até lá, em vez de esbarrar numa lista em vez de calendário.
// `foco` é o primeiro mês da janela atual (o mês selecionado na URL, ou o
// mais antigo com dado, se ausente).
export default function Calendario({ dias, selecionado, hrefDia,
                                     maxMeses = 0, foco = '', hrefMes }) {
  const habilitados = new Set(dias)
  const todos = [...new Set(dias.map((d) => d.slice(0, 7)))].sort()
  const inicio = foco && todos.includes(foco) ? todos.indexOf(foco) : 0
  const meses = maxMeses > 0 ? todos.slice(inicio, inicio + maxMeses) : todos
  const temSetas = maxMeses > 0 && Boolean(hrefMes) && todos.length > maxMeses
  const temAnterior = temSetas && inicio > 0
  const temProximo = temSetas && inicio + maxMeses < todos.length

  const grade = (
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

  if (!temSetas) return grade

  return (
    <div className="cal-carrossel">
      {temAnterior ? (
        <Link className="icon-btn cal-seta" href={hrefMes(todos[inicio - 1])}
              aria-label="Mês anterior">‹</Link>
      ) : (
        <span className="icon-btn cal-seta off" aria-hidden="true">‹</span>
      )}
      {grade}
      {temProximo ? (
        <Link className="icon-btn cal-seta" href={hrefMes(todos[inicio + 1])}
              aria-label="Mês seguinte">›</Link>
      ) : (
        <span className="icon-btn cal-seta off" aria-hidden="true">›</span>
      )}
    </div>
  )
}
