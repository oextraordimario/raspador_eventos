import Link from 'next/link'
import Drop from './Drop'
import Calendario from './Calendario'
import { PERIODOS } from '../lib/config'

// Filtro de "quando" unificado: os atalhos de período (hoje/fim de semana/7
// dias/próximos) moram dentro do MESMO dropdown do calendário, porque
// respondem à mesma pergunta que um dia específico — dia escolhido substitui
// o período, nunca os dois valem juntos (ver paramsDe em festas/page.jsx).
// Server component, como o Calendario: `href` já chega calculado do pai.
export default function DropData({ periodo, dia, dias, href, maxMeses = 2, mesCal = '' }) {
  return (
    <Drop rotulo="data" aberto={Boolean(dia) || Boolean(mesCal)}
          classeMenu="drop-menu-lista drop-menu-data">
      <div className="cal-atalhos">
        {PERIODOS.map((p) => (
          <Link key={p.chave} className="chip"
                href={href({ periodo: p.chave, dia: '', mesCal: '' })}
                data-on={!dia && periodo === p.chave ? '1' : '0'}>
            {p.rotulo}
          </Link>
        ))}
      </div>
      <Calendario dias={dias} selecionado={dia} maxMeses={maxMeses} foco={mesCal}
                  hrefMes={(mes) => href({ mesCal: mes })}
                  hrefDia={(d) => href({ dia: dia === d ? '' : d })} />
    </Drop>
  )
}
