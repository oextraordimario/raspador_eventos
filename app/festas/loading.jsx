import Esqueleto from '../Esqueleto'

// Trocar de período, de bairro ou de tipo é uma navegação — e é aqui que a
// pessoa sente a espera. Ver NI-50 / app/Esqueleto.jsx.
export default function Carregando() {
  return <Esqueleto n={6} />
}
