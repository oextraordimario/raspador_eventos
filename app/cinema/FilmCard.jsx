import Link from 'next/link'
import Cartaz from './Cartaz'
import { notaFmt } from '../../lib/cinema'

// Card da grade filtrada (com filtro ativo a página troca as faixas por
// isto). O clique abre o detalhe NO site (/cinema/[id]) — quem manda para a
// venda é a página de sessões, horário por horário. No lugar da contagem de
// cinemas (que mora no detalhe) entram a sinopse e a nota do TMDB (NI-36).
export default function FilmCard({ filme }) {
  return (
    <Link className="card fcard" href={`/cinema/${filme.id}`}>
      <Cartaz src={filme.poster_proprio || filme.poster} titulo={filme.titulo}
              tamanhos="(min-width: 900px) 92px, 78px" />
      <div className="body">
        <h3 className="title">{filme.titulo}</h3>
        <div className="venue">{filme.generos}</div>
        {filme.sinopse && <div className="sinopse">{filme.sinopse}</div>}
        <div className="meta">
          {filme.nota != null && <span className="nota">★ {notaFmt(filme.nota)}</span>}
          {filme.duracao_min && <span className="tag tag-src">{filme.duracao_min} min</span>}
          {filme.classificacao && <span className="tag tag-src">{filme.classificacao}</span>}
          {filme.em_pre_venda === 1 && <span className="tag tag-hot">pré-venda</span>}
        </div>
      </div>
    </Link>
  )
}
