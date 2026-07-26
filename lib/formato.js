// Tudo que é data no site é apresentado no fuso de BRASÍLIA, nunca no fuso do
// aparelho de quem acessa. A base guarda ISO UTC (invariante do schema); quem
// abre o site de outro fuso tem que ver o horário da festa, não o dele.
const TZ = 'America/Sao_Paulo'

const partes = (iso) => {
  const fmt = new Intl.DateTimeFormat('pt-BR', {
    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', weekday: 'short', hour12: false,
  })
  const o = {}
  for (const p of fmt.formatToParts(new Date(iso))) o[p.type] = p.value
  return o
}

export const chaveDia = (iso) => {
  const p = partes(iso)
  return `${p.year}-${p.month}-${p.day}`
}

export const hora = (iso) => {
  const p = partes(iso)
  return `${p.hour}h${p.minute !== '00' ? p.minute : ''}`
}

export const diaSemana = (iso) => partes(iso).weekday.replace('.', '')

export const diaMes = (iso) => {
  const p = partes(iso)
  return `${p.day}/${p.month}`
}

// "hoje" e "amanhã" na vida noturna seguem o corte das 6h: uma festa que
// começa 1h de sábado ainda é a noite de sexta. Sem isso, o rótulo do
// agrupamento brigaria com o filtro de período, que usa a mesma regra.
export function rotuloDia(chave, agora = new Date()) {
  const corte = new Date(agora.getTime() - 6 * 3600e3)
  const hoje = chaveDia(corte.toISOString())
  const amanha = chaveDia(new Date(corte.getTime() + 864e5).toISOString())
  if (chave === hoje) return { texto: 'hoje', hoje: true }
  if (chave === amanha) return { texto: 'amanhã', hoje: false }
  return { texto: diaSemana(`${chave}T12:00:00-03:00`), hoje: false }
}

export const reais = (v) =>
  `R$ ${Number(v).toFixed(2).replace('.', ',')}`

// Agrupa a lista por dia local preservando a ordem que a API já devolveu
// (ordenada por start_date).
export function agruparPorDia(eventos) {
  const grupos = []
  for (const ev of eventos) {
    if (!ev.start_date) continue
    const chave = chaveDia(ev.start_date)
    const ultimo = grupos.at(-1)
    if (ultimo?.chave === chave) ultimo.eventos.push(ev)
    else grupos.push({ chave, eventos: [ev] })
  }
  return grupos
}
