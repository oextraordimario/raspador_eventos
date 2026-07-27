// Um filtro sempre visível que abre em dropdown (details/summary — sem JS).
// As opções são <Link> que togglam o valor na URL, então cada clique
// re-renderiza a página; `aberto` deixa o dropdown já aberto quando o grupo
// tem seleção, para a multi-escolha não exigir reabrir a cada clique.
export default function Drop({ rotulo, ativos = 0, aberto = false, children }) {
  return (
    <details className="drop" open={aberto || undefined}>
      <summary>
        {rotulo}
        {ativos > 0 && <span className="drop-n">{ativos}</span>}
        <span className="drop-caret" aria-hidden="true">▾</span>
      </summary>
      <div className="drop-menu">{children}</div>
    </details>
  )
}
