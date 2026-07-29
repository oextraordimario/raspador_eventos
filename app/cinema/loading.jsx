import Esqueleto from '../Esqueleto'

// O cartaz é retrato 2:3 (o flyer é 4:5), então o esqueleto usa a outra forma
// — um placeholder com a proporção errada empurra a lista quando o dado chega.
export default function Carregando() {
  return <Esqueleto n={6} cartaz />
}
