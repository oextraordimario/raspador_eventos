import './globals.css'
import Link from 'next/link'
import { MARCA, ORIGEM } from '../lib/config'
import Tema from './Tema'

export const metadata = {
  metadataBase: new URL(ORIGEM),
  title: {
    default: `${MARCA.nome} — o que rola em ${MARCA.cidade}`,
    template: `%s · ${MARCA.nome}`,
  },
  description: MARCA.descricao,
  // Canônica relativa: o Next resolve './' contra o metadataBase e a rota
  // ATUAL, então cada página aponta para si mesma. Existe por causa do
  // skipTrailingSlashRedirect que o PostHog exige no next.config.mjs (o proxy
  // /ph/ tem endpoints terminados em barra, que o redirect automático
  // quebraria): sem ele o Next mandava /sobre/ → /sobre com 308, e com ele as
  // duas URLs respondem 200. Para um site cuja aposta é ser indexado, isso é
  // conteúdo duplicado — a canônica é quem colapsa o par.
  alternates: { canonical: './' },
  openGraph: {
    type: 'website',
    locale: 'pt_BR',
    siteName: MARCA.nome,
  },
}

export const viewport = {
  // acompanha o tema para a barra do navegador no celular não destoar
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '#0f1311' },
    { media: '(prefers-color-scheme: light)', color: '#eef0f2' },
  ],
}

export default function RootLayout({ children }) {
  return (
    <html lang="pt-BR">
      <body>
        <header className="top">
          <div className="top-inner">
            <div className="brand-row">
              <Link href="/">
                <h1 className="brand">
                  {MARCA.prefixo}
                  <span className="sig">{MARCA.separador}</span>
                  {MARCA.sufixo}
                  <span className="cur">_</span>
                </h1>
              </Link>
              <div className="head-btns">
                <Tema />
              </div>
            </div>
          </div>
        </header>

        <main className="wrap">{children}</main>

        <footer className="foot">
          <Link href="/sobre">sobre</Link> ·{' '}
          <Link href="/filmes">cinema</Link> ·{' '}
          <a href="https://github.com/oextraordimario/raspador_eventos"
             target="_blank" rel="noopener">código</a>
          <br />
          sympla · ingresse · shotgun · zig · ticket and go · instagram · ingresso.com
          <br />
          não vendemos ingresso — cada evento leva para quem está vendendo
        </footer>

      </body>
    </html>
  )
}
