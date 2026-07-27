import Link from 'next/link'

export default function NaoEncontrado() {
  return (
    <div className="empty" style={{ paddingTop: 80 }}>
      <strong>Página não encontrada</strong>
      <span>
        Esse endereço não existe — ou o evento saiu do ar desde a última coleta.
      </span>
      <p style={{ marginTop: 20 }}>
        <Link className="cta" href="/festas">Ver o que tem hoje</Link>
      </p>
    </div>
  )
}
