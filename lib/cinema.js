// Dado curado da página de cinema (NI-35). Mora aqui, não na base: são 8
// cinemas e 4 redes — mapa estático é mais honesto que coluna derivada.

// Rede → cinemas dela (casam por substring com `sessoes.cinema`, que usa os
// apelidos canônicos de scrapers/cinema.py). "Cinema de rua" agrupa os
// independentes — que calham de ser as salas de arte da cidade.
export const REDES = {
  cinemark: { rotulo: 'Cinemark', cinemas: ['Cinemark'] },
  kinoplex: { rotulo: 'Kinoplex', cinemas: ['Kinoplex'] },
  cinesystem: { rotulo: 'Cinesystem', cinemas: ['Cinesystem'] },
  rua: { rotulo: 'cinema de rua', cinemas: ['Cine Brasília', 'Cine Cultura'] },
}

// Presets de horário da UI → janela genérica hora_de/hora_ate da API (hora
// LOCAL de Brasília; `ate` exclusivo). A API aceita qualquer janela — os
// presets são só a cara amigável dela. Escolha ÚNICA de propósito: o backend
// filtra por UMA janela, e "matinê + noite" não é uma janela.
export const HORARIOS = {
  matine: { rotulo: 'matinê (até 15h)', hora_ate: 15 },
  tarde: { rotulo: 'tarde (15–18h)', hora_de: 15, hora_ate: 18 },
  noite: { rotulo: 'noite (18h+)', hora_de: 18 },
}

// Redes marcadas (multi) → lista de cinemas para o param `cinema` da API.
export const redesParaCinemas = (chaves) =>
  chaves.flatMap((c) => REDES[c]?.cinemas ?? [])

// Nota do TMDB (0–10) no formato local: "7,4".
export const notaFmt = (n) => Number(n).toFixed(1).replace('.', ',')

// ── Faixas estilo streaming (heurísticas v1 — spec §3.2) ────────────────────
// Derivadas no front de UMA chamada ao catálogo; filme pode repetir entre
// faixas (como nos streamings). Faixa com menos de MIN_FAIXA não renderiza.

const MIN_FAIXA = 3
const tem = (csv, ...termos) =>
  termos.some((t) => (csv || '').toLowerCase().includes(t.toLowerCase()))

export function montarFaixas(filmes, { agora = new Date() } = {}) {
  const doisDias = new Date(agora.getTime() + 2 * 864e5).toISOString()
  const soArte = (f) => {
    const salas = (f.cinemas || '').split(', ').filter(Boolean)
    return salas.length > 0 &&
      salas.every((c) => c.startsWith('Cine Brasília') || c.startsWith('Cine Cultura'))
  }
  const faixas = [
    { chave: 'alta', titulo: 'Em alta',
      filmes: filmes.filter((f) => f.em_pre_venda !== 1 &&
        (f.cinemas || '').split(', ').filter(Boolean).length >= 3).slice(0, 10) },
    { chave: 'familia', titulo: 'Pra toda a família',
      filmes: filmes.filter((f) => tem(f.generos, 'Animação', 'Família') ||
        f.classificacao === 'Livre' || f.classificacao === '6 anos') },
    { chave: 'medo', titulo: 'Pra te tirar o sono',
      filmes: filmes.filter((f) => tem(f.generos, 'Terror', 'Suspense')) },
    { chave: 'ultima', titulo: 'Última chance',
      filmes: filmes.filter((f) => f.em_pre_venda !== 1 &&
        f.ultima_sessao && f.ultima_sessao <= doisDias) },
    { chave: 'arte', titulo: 'Sessão de arte', filmes: filmes.filter(soArte) },
    { chave: 'prevenda', titulo: 'Pré-venda',
      filmes: filmes.filter((f) => f.em_pre_venda === 1) },
  ]
  const ativas = faixas.filter((fx) => fx.filmes.length >= MIN_FAIXA)

  // Nenhuma heurística é exaustiva (filme "comum" — não família, não
  // terror, pouca distribuição, longe do fim — pode não casar com
  // nenhuma), e uma faixa pequena demais nem chega a aparecer (MIN_FAIXA).
  // Esta pega quem sobrou das faixas REALMENTE exibidas, sem piso mínimo:
  // é a garantia de que todo filme do catálogo aparece na vitrine.
  const cobertos = new Set(ativas.flatMap((fx) => fx.filmes.map((f) => f.id)))
  const sobra = filmes.filter((f) => !cobertos.has(f.id))
  if (sobra.length > 0) {
    ativas.push({ chave: 'tambem', titulo: 'Também em cartaz', filmes: sobra })
  }
  return ativas
}
