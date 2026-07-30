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
// A limpeza do título NÃO mora mais aqui.
//
// Ela nasceu neste arquivo em 2026-07-27 (`tituloLimpo`) para tirar do card a
// data que o organizador repete no nome — "Forró na Varanda | 28.07 | Varanda
// do Contexto" — e consertava só o site. Em 2026-07-29 virou
// `base/texto.titulo_limpo`, aplicada na ESCRITA da prata (NI-33): o `nome` que
// a API devolve já vem limpo, quem consulta pelo MCP recebe o mesmo título que
// quem abre o site, e o slug da URL não pode divergir do <h1> porque os dois
// saem da mesma string.
//
// Duas cópias da regra em duas linguagens era o risco de verdade: a primeira
// divergência entre elas não seria um título feio, seria um endereço quebrado.
//
// Spec: docs/specs/20260729_urls-semanticas/ §5.

// Hora do evento. Alguns eventos chegam sem horário — o do Instagram, quando
// o flyer só traz a data, cai em 00:00 — e mostrar "00h" ali afirma que a
// festa começa à meia-noite, que é diferente de não saber. Sem hora crível,
// devolve vazio e o card simplesmente não mostra o horário.
export function horaOuNada(iso, fonte) {
  const p = partes(iso)
  if (fonte === 'instagram' && p.hour === '00' && p.minute === '00') return ''
  return hora(iso)
}

// ---------------------------------------------------------------------------
// Janela de data no formato do Google Agenda (NI-51).
//
// É a única função daqui que quer UTC mesmo: o template do Google recebe
// `AAAAMMDDTHHMMSSZ`, e a base já guarda ISO UTC por invariante do schema —
// então a conversão é só apagar os separadores.
const utcCompacto = (iso) =>
  new Date(iso).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')

// Quanto tempo o evento ocupa na agenda de quem clicou. `end_date` vem
// inconsistente de algumas fontes (o CLAUDE.md manda filtrar por start_date
// justamente por isso), e um evento de três anos no calendário de alguém é
// pior que uma estimativa errada por uma hora: só se aceita um fim que esteja
// DEPOIS do início e dentro de 12h dele; fora disso, início + 4h.
const DURACAO_PADRAO = 4 * 3600e3
const LIMITE_CRIVEL = 12 * 3600e3

export function janelaAgenda(inicio, fim) {
  const ini = new Date(inicio)
  const cand = fim ? new Date(fim) : null
  const dur = cand ? cand.getTime() - ini.getTime() : 0
  const term = cand && dur > 0 && dur <= LIMITE_CRIVEL
    ? cand
    : new Date(ini.getTime() + DURACAO_PADRAO)
  return `${utcCompacto(ini.toISOString())}/${utcCompacto(term.toISOString())}`
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
