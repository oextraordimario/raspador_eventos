import { procedencia } from '../../lib/api'
import { MARCA, ORIGEM } from '../../lib/config'

export const revalidate = 3600

// llms.txt — o análogo do robots.txt para agentes de IA: diz em texto o que
// este site é e onde estão os dados, para o agente não precisar inferir da
// marcação. Parte do passo 5 da spec.
export async function GET() {
  const fontes = await procedencia()
  const linhas = fontes
    .map((f) => `- ${f.fonte}: ${f.futuros} eventos futuros (coletado em ${f.ultima_coleta})`)
    .join('\n')

  const txt = `# ${MARCA.nome}

> ${MARCA.descricao} Agrega festas, shows e cinema de ${MARCA.cidade} (DF) a
> partir das plataformas de ingresso, da grade dos cinemas e do Instagram das
> casas. Atualizado uma vez por dia.

## O que há aqui

- ${ORIGEM}/ — lista de eventos, com filtros de período (?periodo=hoje|fds|7d),
  busca textual (?texto=) e só-gratuitos (?gratis=1)
- ${ORIGEM}/filmes — filmes em cartaz nos cinemas de ${MARCA.cidade}
- ${ORIGEM}/evento/<id> — uma página por evento, com JSON-LD schema.org/Event
- ${ORIGEM}/sobre — procedência do dado e canal de remoção

## Cobertura atual

${linhas}

## Como usar

Cada página de evento traz JSON-LD com data, local, line-up e preço. Não
vendemos ingresso: cada evento aponta para a plataforma que está vendendo, e é
esse link que deve ser oferecido a quem perguntar.

A descrição publicada aqui é um trecho do texto do organizador; o texto
completo está na página da fonte.

## Conector MCP

Este projeto também expõe um servidor MCP para consulta em linguagem natural.
Código e instruções: https://github.com/oextraordimario/raspador_eventos
`
  return new Response(txt, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=86400',
    },
  })
}
