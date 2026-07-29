import './globals.css'
import Link from 'next/link'
import { Space_Grotesk, Fira_Code } from 'next/font/google'
import { MARCA, ORIGEM } from '../lib/config'
import Tema from './Tema'
import LinkFeedback from './LinkFeedback'

// Auto-hospedadas pelo next/font em vez do @import do Google Fonts que havia
// no globals.css: aquele bloqueava a renderização e exigia uma conexão a um
// terceiro antes do primeiro pixel — caro no 4G, que é onde este site é usado
// de verdade. `display: swap` garante texto visível enquanto a fonte chega.
const sans = Space_Grotesk({
  subsets: ['latin'], weight: ['400', '500', '600', '700'],
  display: 'swap', variable: '--fonte-sans',
})
const mono = Fira_Code({
  subsets: ['latin'], weight: ['400', '500', '600', '700'],
  display: 'swap', variable: '--fonte-mono',
})

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
  // Light é o padrão do site (não segue o sistema); quando a pessoa alterna
  // no botão, o Tema.jsx atualiza esta meta tag junto com o data-theme.
  themeColor: '#eef0f2',
}

export default function RootLayout({ children }) {
  return (
    <html lang="pt-BR" className={`${sans.variable} ${mono.variable}`}>
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
            <nav className="head-nav">
              <Link href="/festas">festas &amp; shows</Link>
              <Link href="/filmes">cinema</Link>
            </nav>
          </div>
        </header>

        <LinkFeedback />

        <main className="wrap">{children}</main>

        <footer className="foot">
          <Link href="/sobre">sobre</Link> ·{' '}
          <a href="https://github.com/oextraordimario/raspador_eventos"
             target="_blank" rel="noopener">código</a>
          <br />
          não vendemos ingresso — cada evento leva para quem está vendendo
        </footer>

      </body>
    </html>
  )
}
