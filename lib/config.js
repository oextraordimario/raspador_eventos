// Identidade do produto — TUDO num lugar só, de propósito.
//
// O nome `role.bsb` é PROVISÓRIO (decisão do autor em 2026-07-26): destrava o
// trabalho agora, e se o projeto ficar sério o nome definitivo será repensado.
// A spec exige que ele não se espalhe pelo código, senão renomear deixa de ser
// decisão e vira refatoração. Nenhum outro arquivo deve escrever o nome
// literal — importe daqui.

export const MARCA = {
  nome: 'role.bsb',
  // partes separadas para o header poder colorir o ponto sem hardcode
  prefixo: 'role',
  separador: '.',
  sufixo: 'bsb',
  descricao: 'Tudo o que vai rolar em Brasília, num lugar só.',
  cidade: 'Brasília',
}

// Origem pública do site. Em produção vem da env da Vercel; no dev cai no
// localhost. Usada pelo sitemap e pelo JSON-LD, que exigem URL absoluta.
export const ORIGEM =
  process.env.NEXT_PUBLIC_ORIGEM ||
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : 'http://localhost:3000')

// Base da API de leitura em Python (api/dados.py). Mesma origem em produção —
// o vercel.json roteia /api/dados/* para a função.
export const API =
  process.env.API_INTERNA || `${ORIGEM}/api/dados`

// Atalhos de período do filtro de data (dentro do drop de calendário).
// "próximos" saiu daqui: virou o botão externo "todos os eventos", ao lado
// de "perto de mim" — continua existindo como valor de `periodo` (NI-41: é o
// default de quem busca por texto), só não mora mais nesta lista. "7d"
// também saiu por pedido direto (deixou de ser um filtro exposto), mas o
// backend (`api/dados.py`) continua entendendo o valor — é o default interno
// da home e do sitemap (`app/page.jsx`, `app/sitemap.js`).
export const PERIODOS = [
  { chave: 'hoje', rotulo: 'hoje' },
  { chave: 'amanha', rotulo: 'amanhã' },
  { chave: 'fds', rotulo: 'fim de semana' },
  { chave: 'semana', rotulo: 'próxima semana' },
]

// Festa & balada × show & festival (NI-44). O rótulo do chip é mais longo que
// o valor de propósito: "festa" sozinho não diz que baladas entram junto.
// Quem NÃO tem rótulo aparece nos dois — ver enriquecer._classificar_tipo.
export const TIPOS = [
  { chave: 'festa', rotulo: 'festas & baladas' },
  { chave: 'show', rotulo: 'shows & festivais' },
]

// O período assumido quando a URL não diz qual é. Depende de haver busca
// textual: sem texto, a pergunta é "o que rola hoje?"; com texto, é "quando
// tem isso?" — e responder só por hoje devolve zero resultados com cara de
// busca quebrada, que foi exatamente o bug do NI-41.
export const periodoPadrao = (texto) => (texto ? 'proximos' : 'hoje')
