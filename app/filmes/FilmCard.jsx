import Link from 'next/link'
import Cartaz from './Cartaz'

// Card da grade filtrada (com filtro ativo a página troca as faixas por
// isto). O clique agora abre o detalhe NO site (/filmes/[id]) — quem manda
// para a venda é a página de sessões, horário por horário. A contagem de
// cinemas saiu do card (mora no detalhe); a sinopse entra aqui quando o
// NI-36 aterrissar.
export default function FilmCard({ filme }) {
  return (
    <Link className="card fcard" href={`/filmes/${filme.id}`}>
      <Cartaz src={filme.poster} titulo={filme.titulo}
              tamanhos="(min-width: 900px) 92px, 78px" />
      <div className="body">
        <h3 className="title">{filme.titulo}</h3>
        <div className="venue">{filme.generos}</div>
        <div className="meta">
          {filme.duracao_min && <span className="tag tag-src">{filme.duracao_min} min</span>}
          {filme.classificacao && <span className="tag tag-src">{filme.classificacao}</span>}
          {filme.em_pre_venda === 1 && <span className="tag tag-hot">pré-venda</span>}
        </div>
      </div>
    </Link>
  )
}
