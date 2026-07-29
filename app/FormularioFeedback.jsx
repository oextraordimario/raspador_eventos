import Link from 'next/link'

export const TIPOS_FEEDBACK = [
  { valor: 'bug', rotulo: 'achei um erro' },
  { valor: 'casa', rotulo: 'quero minha casa aqui' },
  { valor: 'sugestao', rotulo: 'tenho uma sugestão' },
  { valor: 'outro', rotulo: 'outro assunto' },
]

// Campos do canal de feedback (NI-52), compartilhados entre a página
// /feedback (fallback sem JS) e o ModalFeedback (experiência com JS). O
// <form> é NATIVO, sem fetch, method="post" — é o único jeito de o envio
// funcionar sem JS; quem responde é a função Python (api/dados.py), que
// redireciona de volta para /feedback com ?ok=1 ou ?erro=.
export default function FormularioFeedback({ pagina = '' }) {
  return (
    <form className="form" method="post" action="/api/dados/feedback">
      <label className="campo">
        <span className="campo-nome">assunto</span>
        <select name="tipo" defaultValue="bug" required>
          {TIPOS_FEEDBACK.map((t) => (
            <option key={t.valor} value={t.valor}>{t.rotulo}</option>
          ))}
        </select>
      </label>

      <label className="campo">
        <span className="campo-nome">o que aconteceu</span>
        <textarea name="mensagem" rows={6} maxLength={2000} required
                  placeholder="Conte com as suas palavras. Se for sobre um evento específico, cola o link dele aqui." />
      </label>

      <label className="campo">
        <span className="campo-nome">
          contato <em>(opcional)</em>
        </span>
        <input name="contato" type="text" maxLength={200}
               placeholder="e-mail ou @ do Instagram" />
        <small>
          Só serve pra gente te responder sobre isto. Fica numa base
          privada e sai se você pedir (veja o{' '}
          <Link href="/sobre" className="link-sublinhado">sobre</Link>).
        </small>
      </label>

      {/* honeypot: pessoa nenhuma vê este campo (o CSS o tira da tela).
          Preenchido = robô, e a resposta é de sucesso, sem gravar. */}
      <div className="isca" aria-hidden="true">
        <label>
          não preencha este campo
          <input name="site" type="text" tabIndex={-1} autoComplete="off" />
        </label>
      </div>

      <input type="hidden" name="pagina" value={pagina} />
      <button className="cta" type="submit">enviar</button>
    </form>
  )
}
