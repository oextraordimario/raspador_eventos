// O detalhe abre a partir de um clique no card — a espera aqui é a mais
// sentida de todas, porque a pessoa já decidiu e está esperando o preço.
// O esqueleto imita a ordem real da página: flyer, título, quando, onde.
export default function Carregando() {
  return (
    <>
      <span className="voltar sk-texto">← voltar</span>
      <article className="doc" aria-hidden="true">
        <div className="hero sk" />
        <div className="sk sk-linha" style={{ width: '80%', height: 28 }} />
        <div className="sk sk-linha" style={{ width: '35%', height: 15 }} />
        <div className="sk sk-linha" style={{ width: '55%', height: 15 }} />
        <div className="sk sk-linha" style={{ width: '100%', height: 96 }} />
      </article>
    </>
  )
}
