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

// ---------------------------------------------------------------------------
// Limpeza do título publicado pela fonte.
//
// O organizador enfia a data no nome do evento: "Forró na Varanda | 28.07 |
// Varanda do Contexto". No card isso rouba as duas linhas de título e repete
// uma informação que já está na coluna do dia — e some com o nome de verdade.
//
// DÍVIDA CONHECIDA: o lugar certo disto é a derivação (`derivar.py`), porque
// o nome limpo serve igualmente ao agente que consulta pelo MCP; aqui ele
// conserta só o site. Ficou na apresentação para não mexer na base junto com
// a mudança visual. Ver backlog.
//
// A regra é deliberadamente conservadora: só remove um trecho de data quando
// ele está ISOLADO por um separador. É o que impede de estragar "Rock dos
// 80/90", "Baile 24/7" ou "Aniversário 10/10 anos" — na dúvida, não mexe.
const DIA_MES = String.raw`(?:0?[1-9]|[12]\d|3[01])\s*[\/.\-]\s*(?:0?[1-9]|1[0-2])(?:\s*[\/.\-]\s*(?:\d{2}|\d{4}))?`
const SEP = String.raw`[|–—\-·]`
const SO_DATA = new RegExp(`^\\s*${DIA_MES}\\s*$`)

export function tituloLimpo(nome) {
  if (!nome) return nome
  let t = nome
  // segmentos entre barras/travessões que sejam APENAS data
  t = t.split(/\s*[|–—]\s*/).filter((p) => !SO_DATA.test(p)).join(' | ')
  // data cercada por separador no meio ou no fim
  t = t.replace(new RegExp(`\\s*${SEP}\\s*${DIA_MES}\\s*(?=${SEP}|$)`, 'g'), ' ')
  // data logo no começo ("28/07 - Festa da Firma")
  t = t.replace(new RegExp(`^\\s*${DIA_MES}\\s*${SEP}\\s*`), '')
  // separador órfão nas pontas e espaço duplicado que a remoção deixou
  t = t.replace(new RegExp(`^\\s*${SEP}\\s*|\\s*${SEP}\\s*$`, 'g'), '')
       .replace(/\s{2,}/g, ' ').trim()
  return t || nome   // se a regra comeu tudo, o original volta
}

// Hora do evento. Alguns eventos chegam sem horário — o do Instagram, quando
// o flyer só traz a data, cai em 00:00 — e mostrar "00h" ali afirma que a
// festa começa à meia-noite, que é diferente de não saber. Sem hora crível,
// devolve vazio e o card simplesmente não mostra o horário.
export function horaOuNada(iso, fonte) {
  const p = partes(iso)
  if (fonte === 'instagram' && p.hour === '00' && p.minute === '00') return ''
  return hora(iso)
}

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
