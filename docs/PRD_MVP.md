# PRD — MVP: Eventos de Brasília em Linguagem Natural

> **Status:** MVP em construção. Documento prospectivo — define para onde o produto
> vai a partir da PoC validada.
> **Fonte da verdade:** este documento. O `docs/PRD_POC.md` vira registro histórico
> da prova de conceito e não deve mais ser usado para planejar.
> **Última atualização:** 2026-07-06

---

## 1. Visão e problema

Descobrir "o que tem pra fazer hoje à noite em Brasília" hoje exige **pingar de
site em site** — Sympla, Ingresse, Shotgun, Instagram — cada um com sua busca
capenga, sem linguagem natural, e no caso do Sympla com uma **UX sofrível**. Ninguém
tem paciência de varrer tudo, então a pessoa vê só um pedaço do que está rolando e
decide no escuro.

A proposta do MVP é fazer isso **desaparecer dentro do agente de IA que a pessoa já
usa**. Ela pergunta — *"quais festas de pagode tem neste fim de semana em Brasília?"* —
e o agente responde com eventos reais (data, local, link), tendo por baixo uma base
unificada e limpa das três plataformas. Sem abrir site nenhum, sem aprender filtro
nenhum.

A ambição de longo prazo é que isso funcione **sem a pessoa configurar nada**: o
raspador surge naturalmente quando ela pergunta ao agente, porque o agente encontra
o conteúdo do jeito que já encontra qualquer coisa na web. Esse é o norte
"invisível-first" (seção 4).

## 2. Escopo

**Dentro (MVP lançado):**
- **Cidade:** apenas **Brasília (DF)**.
- **Tipo de evento:** **festas, baladas e shows** (vida noturna / música).

**Fora (por ora):**
- Outras cidades. **Porém o schema nasce cidade-aware** — nada hardcoded para
  "Brasília" — para que ligar uma cidade nova seja "acender um parâmetro", não
  reescrever o sistema. A decisão de expandir fica para depois de o MVP provar valor
  em uma cidade.
- Outros tipos de evento (cursos, workshops, cultural, corporativo).
- Compra de ingressos, autenticação, pagamentos.
- App/site como produto principal (o produto é invisível; "cara própria" só entra se
  se provar vantajosa — ver seção 4).

**Princípio:** o invisível-first premia **profundidade, não largura**. Uma cidade
respondida excepcionalmente bem gera muito mais confiança (de agente e de usuário)
do que dez cidades rasas e furadas. Não generalizar escopo sem pedido explícito.

## 3. Proposta de valor e moat

O agente já consegue buscar direto no Sympla. Então a pergunta central do produto é:
**por que a resposta agregada é melhor do que ir na fonte?** O valor não é *acesso*,
é **qualidade e esforço da resposta**:

1. **Agregação num lugar só.** Tudo o que está rolando em Brasília numa resposta,
   sem pingar de site em site para não perder nada.
2. **Usabilidade em linguagem natural.** Pergunta e resposta, fim do passeio pelas
   páginas de busca ruins (o Sympla em especial).
3. **Personalização.** O agente aprende o que a pessoa gosta (curte pagode, detesta
   sertanejo) e filtra por ela — diminuindo o esforço de garimpar. *Isso mora do
   lado do agente*, mas só funciona se a base **entregar sinal estruturado** para ele
   filtrar (as tags de gênero/vibe — ver v2 abaixo). Personalização é, portanto, um
   benefício direto da camada de enriquecimento.
4. **Limpeza e unificação.** Schema único cross-fonte, ruído removido, o mesmo evento
   anunciado em duas plataformas colapsado numa resposta só.

### Camada de enriquecimento — faseada

O coração do moat é enriquecer o evento **no momento da ingestão** com o que a fonte
*não entrega de graça*. Isso é deliberadamente **faseado** para não carregar custo
antes de provar valor:

- **v1 — regras.** Dedupe cross-fonte + filtro de ruído por heurística/palavras-chave
  (o `themes=99` do Sympla deixa passar anúncio/curso). Barato, sem LLM. Limitação
  conhecida: "festa de pagode" depende de o nome do evento conter a palavra —
  cobertura pior.
- **v2 — LLM.** Um LLM barato (ex.: Haiku) na ingestão classifica **gênero/vibe**
  (pagode, techno, sertanejo, funk, forró...), responde "isso é vida noturna de
  verdade? sim/não" e ajuda no dedupe. É o que faz "festa de pagode" funcionar de
  fato e o que alimenta a personalização. Entra quando já houver uso que justifique
  o custo de LLM por evento.

## 4. Modelo de distribuição

**Decisão nº 1: híbrido, invisível-first.** Duas portas para a mesma base:

- **Porta A — ser uma _ferramenta_ que o agente chama** (MCP/connector/API). Reaproveita
  a camada de consulta que já existe. Preciso e estruturado, mas exige um passo de
  instalação (ainda que leve) e/ou estar listado num diretório de connectors.
- **Porta B — ser _conteúdo_ que o agente acha.** Um site público com uma página por
  evento e páginas de lista (cidade/gênero/data) marcadas em **JSON-LD
  `schema.org/Event`** (o mesmo formato que já parseamos do Shotgun) + `llms.txt` +
  sitemap. Quando alguém pergunta ao agente, a busca web dele acha e lê. **Zero
  configuração, funciona em qualquer agente.** É o invisível-first na forma pura.

O produto é **invisível por padrão** (alimenta agentes); "cara própria" (site/app para
humanos) só entra se provar vantagem — e, se entrar, reaproveita as mesmas páginas da
Porta B.

### Risco estrutural: cold-start de descoberta

Ser "conteúdo achável" só vale se a busca do agente **chegar** até você. Um domínio
novo não ranqueia tão cedo para "festas em Brasília hoje" — quem ganha essa busca são
as próprias fontes (Sympla, Instagram, blogs). Ou seja: no começo, "achável de graça"
vem de **estar onde o agente já é apontado** (diretório de connectors, `llms.txt`
divulgado, links semeados por nós), não de SEO orgânico puro, que é o jogo longo. O
invisível-first **amadurece na Fase 2**, não no dia 1. Ver seção 8.

### Os anéis de descoberta

A distribuição cresce em anéis concêntricos de confiança, e cada anel é o critério de
sucesso de uma fase (seção 6):

| Anel | Quem descobre/usa | Fase |
|------|-------------------|------|
| Eu | dogfooding do próprio autor | 0 |
| Um conhecido | amigo instala o MCP e usa | 1 |
| Um estranho | descobre organicamente e usa | 2 |

Um anel só faz sentido depois que o de dentro fechou.

## 5. Arquitetura

**Duas portas, uma base.** Seja qual porta vencer, ambas leem do mesmo lugar. Por isso
o alicerce é direção-agnóstico e as portas são camadas finas em cima dele.

**Separação write-path × read-path** (imposta pela escolha de serverless gerenciado):

```
  WRITE (raspagem — processo pesado, Playwright/Chromium)
    [ Sympla ]  [ Ingresse ]  [ Shotgun ]
         └───────────┬───────────┘
                     ▼
        raspar → normalizar → enriquecer (regras v1 / LLM v2)
                     │  UPSERT
                     ▼
  ┌─────────────────────────────────────────────┐
  │  BASE unificada + índice textual             │   Fase 0: SQLite local
  │  (schema cidade-aware, chave <fonte>:<id>)   │   Fase 1+: Postgres (Neon)
  └─────────────────────────────────────────────┘
                     │  SELECT
                     ▼
  READ (serve — leve, escala a zero)
    ┌──────────────────────┐   ┌──────────────────────────┐
    │ Porta A: MCP          │   │ Porta B: páginas públicas │
    │ (stdio local → HTTP   │   │ JSON-LD + llms.txt        │
    │  remoto na Fase 1)    │   │ (Fase 2)                  │
    └──────────────────────┘   └──────────────────────────┘
                     ▼
          ChatGPT / Claude / qualquer agente
```

- **Write-path** roda onde há runtime completo para o Chromium do Shotgun. Fase 0: na
  mão, local. Fase 1: **GitHub Actions agendado** (cron gerenciado, roda Playwright,
  faz UPSERT no Postgres — sem VPS para cuidar). Serverless **não** serve para o
  write por causa do navegador.
- **Read-path** é onde o serverless brilha (escala a zero, barato, sempre no ar).
- **A técnica de raspagem** (herdada da PoC): interceptar a API JSON interna do
  front, não parsear HTML. Sympla e Ingresse via HTTP puro; **Shotgun exige
  Playwright** (bloqueia HTTP puro com 429 e renderiza via RSC).

## 6. Roadmap por fases

Cada fase tem escopo enxuto e um **critério de sucesso binário e honesto** — nunca se
constrói a fase seguinte no escuro.

### Fase 0 — Validação local (próximas semanas, custo zero)

A porta já existe: o **MCP stdio local**. O consumidor é o **próprio agente do autor**.
- **Escopo:** melhorar cobertura/qualidade da raspagem das 3 fontes; regras v1 de
  dedupe + filtro de ruído; rodar o scraper **na mão, 1x/dia**; base **SQLite local**.
- **Sem** GitHub Actions, **sem** serverless, **sem** porta pública, **sem** nuvem paga.
- **Critério de sucesso:** nas próximas semanas, quando o autor quiser saber "o que tem
  hoje em Brasília", ele **abre o agente em vez de abrir o Sympla — e confia na
  resposta**. Dogfooding de um usuário só, o mais exigente.

### Fase 1 — Primeira porta pública (quando a Fase 0 provar valor)

- **Escopo:** subir o alicerce hospedado — migrar a base de SQLite para **Postgres
  gerenciado (Neon, free tier)**; automatizar a raspagem via **GitHub Actions**; expor
  a base como **MCP remoto HTTP** (connector). Aumentar cadência se necessário.
- **Portão técnico:** a migração SQLite→Postgres (FTS5 → `tsvector`/`pg_trgm`;
  o `norm_ts` do `consulta.py` migra junto). Retrabalho pontual, mas real.
- **Critério de sucesso:** **um conhecido** (amigo a quem o autor mostrou o sistema)
  instala o MCP e passa a usar.

### Fase 2 — Invisível-first de verdade (superfície achável)

- **Escopo:** páginas públicas por evento e por lista (cidade/gênero/data) com **JSON-LD
  `schema.org/Event`**, `llms.txt` e sitemap, servidas pela camada serverless. Semear
  descoberta (diretórios, `llms.txt` divulgado, links).
- **Critério de sucesso:** **um estranho** — alguém que o autor não conhece — descobre
  o sistema organicamente (via busca do próprio agente) e usa.

### Depois (fora do MVP)

- **Enriquecimento por LLM (v2):** gênero/vibe, filtro de ruído fino, dedupe assistido
  → destrava "festa de pagode" e a personalização.
- **Expansão multi-cidade:** acender novas cidades no schema já cidade-aware.
- **Cara própria** para humanos, se provar vantagem.
- Aumento de frescor/cadência conforme o uso crescer.

## 7. Decisões técnicas travadas

- **Distribuição:** híbrido, invisível-first; cara própria opcional.
- **Banco:** **SQLite** na Fase 0; **Postgres no Neon** (free tier) a partir da Fase 1.
- **Automação de raspagem:** **na mão** na Fase 0; **GitHub Actions** a partir da Fase 1
  (não antes — Actions substitui o "rodar na mão", não o precede).
- **Serve:** serverless gerenciado (read-path). Write-path fica fora do serverless por
  causa do Playwright.
- **Cadência:** **1x/dia** por ora; aumentar conforme o projeto crescer. Prioridade é
  provar com dados reais, não frescor de minuto.
- **Custo:** só **free tier + soluções locais**. Nada de cloud paga nas próximas semanas.
- **Enriquecimento:** faseado — regras na v1, LLM na v2.
- **Escopo:** Brasília-only, festas/baladas/shows, schema cidade-aware.

## 8. Riscos e mitigações

- **Cold-start de descoberta** (o principal): domínio novo não é achado pela busca do
  agente tão cedo. Mitigação: não apostar o MVP em SEO orgânico; distribuir pelos anéis
  (eu → conhecido → estranho), semear presença onde o agente já olha, tratar a Porta B
  como jogo longo.
- **Moat fraco vs. as próprias fontes:** se a resposta agregada não for claramente
  melhor que ir no Sympla, não há razão de existir. Mitigação: a camada de
  enriquecimento (agregação + limpeza + gênero/vibe + personalização) é o produto, não
  a raspagem.
- **Estabilidade das APIs internas:** não são contratos públicos, mudam sem aviso.
  Mitigação: raspador tolerante a campos ausentes + monitoramento; `discover_sympla.py`
  como ferramenta de reconhecimento quando um site muda.
- **Bloqueio / rate-limiting** (Shotgun já deu 429): headers realistas, ritmo educado,
  Playwright onde necessário.
- **Ruído na base:** `themes=99` do Sympla deixa passar anúncio/curso; `end_date` às
  vezes inconsistente na origem (filtrar por `start_date`). Mitigação: filtro v1 por
  regra, filtro v2 por LLM.
- **Frescor vs. custo:** cadência que mantém útil sem abusar das fontes nem gerar custo.
  Mitigação: 1x/dia é suficiente para vida noturna no MVP.
- **Legal / Termos de Uso:** raspagem de catálogo público vs. ToS de cada plataforma —
  a avaliar antes de qualquer operação comercial.

## 9. Não-objetivos (MVP)

- Outras cidades além de Brasília no lançamento.
- Outros tipos de evento além de festas/baladas/shows.
- App ou site como produto principal (produto é invisível).
- Compra de ingressos, contas de usuário, pagamentos.
- LLM na ingestão no lançamento (é v2).
- Automação de raspagem em nuvem nas primeiras semanas (é Fase 1).
- Cobertura 100% garantida do catálogo desde o dia 1.

## 10. Métricas de sucesso

A métrica do MVP **é a escada de anéis** — cada fase só avança quando o anel de dentro
fechou:

- **Fase 0 — eu:** o autor troca o Sympla pelo agente para descobrir a noite de
  Brasília, e confia na resposta.
- **Fase 1 — um conhecido:** um amigo instala o MCP e usa de verdade.
- **Fase 2 — um estranho:** alguém desconhecido descobre organicamente e usa.

Sinais qualitativos de apoio (não são o gatilho de fase): as respostas do agente batem
com o que está realmente à venda (precisão) e cobrem o que deveriam (recall). Quando o
LLM v2 entrar, medir se "festa de pagode" passa a retornar festas de pagode que **não
têm a palavra no nome**.

## 11. Documentos de referência

- `docs/PRD_POC.md` — registro histórico da prova de conceito (validação da raspagem).
- `docs/PROXIMOS_PASSOS.md` — backlog priorizado.
- `docs/TESTE_MCP.md` — como plugar o MCP nos clientes de IA.
