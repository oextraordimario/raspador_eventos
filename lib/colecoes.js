// Coleções sazonais (NI-47) — curadoria versionada, como a watchlist do
// Instagram. É açúcar sobre a busca que já existe: o chip só preenche
// `?texto=` com uma consulta pré-montada. Zero backend, zero schema.
//
// O mapa É o produto aqui. A qualidade do chip é a qualidade dos termos, e
// eles se calibram contra a base real ("arraiá" com e sem acento aparece; o
// FTS já normaliza, mas os dois ficam para o caso de a configuração mudar).
//
// `meses` é a janela do ANO em que o chip faz sentido (1 = janeiro). Fora
// dela ele não renderiza: um chip de réveillon em março é ruído que ocupa a
// linha dos filtros que funcionam. A janela começa ANTES da data do evento de
// propósito — quem procura festa junina em junho está comprando ingresso para
// julho, e quem procura réveillon em novembro idem.
export const COLECOES = [
  {
    chave: 'halloween',
    rotulo: 'halloween',
    termos: 'halloween OR terror OR fantasia OR macabr',
    meses: [9, 10],
  },
  {
    chave: 'reveillon',
    rotulo: 'réveillon',
    termos: 'réveillon OR reveillon OR "ano novo" OR virada OR "31/12"',
    meses: [11, 12],
  },
  {
    chave: 'carnaval',
    rotulo: 'carnaval',
    termos: 'carnaval OR carnavalesco OR bloco OR blocos OR "pré-carnaval"',
    meses: [12, 1, 2],
  },
]

// O mês é o de BRASÍLIA, não o do servidor — o site inteiro segue esse fuso, e
// numa função serverless em UTC a virada do mês chegaria três horas cedo.
export function colecoesAgora(agora = new Date()) {
  const mes = Number(new Intl.DateTimeFormat('en', {
    timeZone: 'America/Sao_Paulo', month: 'numeric',
  }).format(agora))
  return COLECOES.filter((c) => c.meses.includes(mes))
}
