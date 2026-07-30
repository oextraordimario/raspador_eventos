import Esqueleto from '../../Esqueleto'

// Mora num route group `(lista)` — que não aparece na URL — para a fronteira de
// Suspense cobrir SÓ a lista. Em `app/cinema/` ela cobria também o `[slug]`, e aí
// o Next despachava um shell 200 antes de resolver o filme: o 308 do endereço
// antigo e o 404 do filme inexistente viravam redirecionamento de CLIENTE, que o
// buscador lê como página existente. Medido no build de produção em 29/07.
//
// O cartaz é retrato 2:3 (o flyer é 4:5), então o esqueleto usa a outra forma
// — um placeholder com a proporção errada empurra a lista quando o dado chega.
export default function Carregando() {
  return <Esqueleto n={6} cartaz />
}
