'use client'

import { useState } from 'react'
import Link from 'next/link'

export const TIPOS_FEEDBACK = [
  { valor: 'bug', rotulo: 'achei um erro' },
  { valor: 'casa', rotulo: 'meu evento não está listado' },
  { valor: 'sugestao', rotulo: 'tenho uma sugestão' },
  { valor: 'outro', rotulo: 'outro assunto' },
]

const PADRAO = 'bug'

// Um placeholder por assunto — o textarea muda de dica conforme o `select`,
// mas sem JS (form ainda funciona: é só progressive enhancement) ele fica
// parado no texto do assunto padrão (PADRAO), que é o que o servidor já
// renderiza de cara.
const PLACEHOLDERS = {
  bug: 'Conte com as suas palavras o que aconteceu. Se for sobre um evento específico, cola o link dele aqui.',
  casa: 'Qual é o nome do evento ou da casa, quando é e onde? Se tiver um link (Instagram, site do ingresso), cola aqui.',
  sugestao: 'Conta sua ideia com detalhes — o que você mudaria e por quê.',
  outro: 'Conte com as suas palavras.',
}

// Campos do canal de feedback (NI-52), compartilhados entre a página
// /feedback (fallback sem JS) e o ModalFeedback (experiência com JS). O
// <form> é NATIVO, sem fetch, method="post" — é o único jeito de o envio
// funcionar sem JS; quem responde é a função Python (api/dados.py), que
// redireciona de volta para /feedback com ?ok=1 ou ?erro=.
export default function FormularioFeedback({ pagina = '', desabilitado = false }) {
  const [tipo, setTipo] = useState(PADRAO)

  return (
    <form className="form" method="post" action="/api/dados/feedback">
      <label className="campo">
        <span className="campo-nome">assunto</span>
        <select name="tipo" defaultValue={PADRAO} required
                onChange={(e) => setTipo(e.target.value)}>
          {TIPOS_FEEDBACK.map((t) => (
            <option key={t.valor} value={t.valor}>{t.rotulo}</option>
          ))}
        </select>
      </label>

      <label className="campo">
        <span className="campo-nome">o que aconteceu</span>
        <textarea name="mensagem" rows={6} maxLength={2000} required
                  placeholder={PLACEHOLDERS[tipo] ?? PLACEHOLDERS[PADRAO]} />
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
      <button className="cta" type="submit" disabled={desabilitado}>
        {desabilitado ? 'enviando…' : 'enviar'}
      </button>
    </form>
  )
}
