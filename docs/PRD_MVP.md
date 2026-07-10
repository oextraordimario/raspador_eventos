# PRD — MVP: Eventos de Brasília em Linguagem Natural

> **Status:** MVP em construção. Documento prospectivo — define para onde o produto
> vai a partir da PoC validada.
> **Fonte da verdade:** este documento. O `docs/PRD_POC.md` vira registro histórico
> da prova de conceito e não deve mais ser usado para planejar.
> **Última atualização:** 2026-07-10 — a Fase 0 ganhou a subetapa **0b (consulta na
> nuvem)**: o dogfooding mostrou que a consulta não pode depender do PC do autor
> estar ligado. Read-path hospedado antecipa-se da Fase 1; raspagem segue manual.

---

## 1. Visão e problema

Descobrir "o que tem pra fazer hoje à noite em Brasília" hoje exige **pingar de
site em site** — Sympla, Ingresse, Shotgun, Instagram — cada um com sua busca
capenga, sem linguagem natural, e no caso do Sympla com uma **UX sofrível**. Ninguém
tem paciência de varrer tudo, então a pessoa vê só um pedaço do que está rolando e
decide no escuro.

**"Mas por que não simplesmente perguntar pro ChatGPT ou pro Claude?"** É a objeção
óbvia — e hoje ela não se sustenta. Perguntar direto ao agente *"o que tem de festa em
Brasília hoje?"* rende resultado fraco: ele **não acha tudo**, se confunde nas buscas,
mistura datas e dá respostas **levemente erradas**. Não é burrice do agente — é que os
dados nas plataformas são **desestruturados e não otimizados para IA**. O raspador é
justamente o **meio-do-caminho**: trata os dados das fontes e os entrega num formato que
o agente entende de primeira. Sem ele, o agente pesquisa no escuro; com ele, responde
sobre uma base limpa e estruturada. **Essa é a razão de existir do produto.**

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
- **Tipos de evento:**
  - **festas, baladas e shows** (vida noturna / música) — **núcleo**;
  - **filmes em cartaz nos cinemas** (Cinemark, Kinoplex, etc.) — entra como
    **subetapa separada** por adicionar complexidade (novas fontes a raspar), mas faz
    parte do MVP: descobrir *"o que está passando nos cinemas de Brasília hoje"* tem o
    **mesmo problema de fundo** (dados espalhados, busca ruim) e é algo que o autor
    quer usar no dogfooding.

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
- **v2 — LLM.** Um LLM **capaz** roda na ingestão para classificar **gênero/vibe**
  (pagode, techno, sertanejo, funk, forró...), responder "isso é vida noturna de
  verdade? sim/não" e ajudar no dedupe. É o que faz "festa de pagode" funcionar de fato
  e o que alimenta a personalização. Duas decisões travadas aqui:
  - **Modelo: Sonnet, não Haiku.** Nos testes do autor em tarefas parecidas, o Haiku
    entregou qualidade **bem pior** e a economia de custo foi **irrisória** — não
    compensa.
  - **Execução: por subagente no Claude Code CLI (ou equivalente), não por API paga.**
    O autor já tem assinatura Anthropic; rodar via API dobraria o custo sem motivo.
  Entra quando já houver uso/insumo que justifique — na prática, junto da etapa de
  Instagram abaixo (é ali que o classificador ganha texto rico para trabalhar).

- **Contexto externo — Instagram (fundamental, porém trabalhoso).** Muita festa tem
  página **enxuta** na plataforma de ingressos: descrição pobre que não deixa claro o
  estilo do evento. Na prática, para entender do que se trata, é preciso ir ao
  **Instagram da festa e/ou da casa**. Sem esse contexto, o raspador dificilmente é
  *realmente* útil para vida noturna — por isso precisa ser **testado já no MVP**. Mas
  fica como **última etapa**, por dar bastante trabalho (achar o @ certo, raspar,
  alimentar o classificador). O texto do Instagram é o principal insumo do
  enriquecimento por LLM acima.

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

**Restrição de disponibilidade** (achado do dogfooding de 2026-07-10): o read-path
**não pode depender do computador do autor estar ligado**. O momento de uso típico da
vida noturna é na rua, à noite, só com o celular — atualizar às 9h de sexta não serve
de nada se às 21h a base estiver num PC desligado. Logo, a base e a camada de consulta
precisam viver na nuvem **já no dogfooding** (Fase 0b). O write-path pode continuar
manual e local: quem raspa é o PC do autor, quando ele quiser; quem serve é a nuvem,
sempre.

**Separação write-path × read-path** (imposta pela escolha de serverless gerenciado —
e agora também pela restrição de disponibilidade acima):

```
  WRITE (raspagem — processo pesado, Playwright/Chromium)
    eventos:   [ Sympla ] [ Ingresse ] [ Shotgun ]   [ Cinemark / Kinoplex … ]
    contexto:  [ Instagram da festa / da casa ]  (última etapa — enriquecimento)
         └────────────────────┬────────────────────┘
                              ▼
        raspar → normalizar → enriquecer (regras v1 / LLM v2: Sonnet via subagente)
                     │  UPSERT
                     ▼
  ┌─────────────────────────────────────────────┐
  │  BASE unificada + índice textual             │   Fase 0a: SQLite local
  │  (schema cidade-aware, chave <fonte>:<id>)   │   Fase 0b+: Postgres (Neon)
  └─────────────────────────────────────────────┘
                     │  SELECT
                     ▼
  READ (serve — leve, escala a zero)
    ┌──────────────────────┐   ┌──────────────────────────┐
    │ Porta A: MCP          │   │ Porta B: páginas públicas │
    │ (stdio local → HTTP   │   │ JSON-LD + llms.txt        │
    │  remoto na Fase 0b)   │   │ (Fase 2)                  │
    └──────────────────────┘   └──────────────────────────┘
                     ▼
          ChatGPT / Claude / qualquer agente
```

- **Write-path** roda onde há runtime completo para o Chromium do Shotgun. Fases
  0a/0b: na mão, local — na 0b o `atualizar.py` continua rodando no PC do autor, mas
  o UPSERT vai direto para a base remota. Fase 1: **GitHub Actions agendado** (cron
  gerenciado, roda Playwright, faz UPSERT no Postgres — sem VPS para cuidar).
  Serverless **não** serve para o write por causa do navegador.
- **Read-path** é onde o serverless brilha (escala a zero, barato, sempre no ar) — e
  o "sempre no ar" é exatamente o que a restrição de disponibilidade exige; por isso
  ele sobe já na Fase 0b, não na Fase 1.
- **A técnica de raspagem** (herdada da PoC): interceptar a API JSON interna do
  front, não parsear HTML. Sympla e Ingresse via HTTP puro; **Shotgun exige
  Playwright** (bloqueia HTTP puro com 429 e renderiza via RSC). **Cinemas** (Cinemark,
  Kinoplex...) e **Instagram** são frentes novas, com técnica a mapear — Instagram em
  especial é frágil e resistente à raspagem (por isso, última etapa).

## 6. Roadmap por fases

Cada fase tem escopo enxuto e um **critério de sucesso binário e honesto** — nunca se
constrói a fase seguinte no escuro.

### Fase 0 — Validação pelo autor (dogfooding)

O consumidor é o **próprio agente do autor**. O dogfooding de 2026-07-09/10 mostrou
que a fase tem **duas subetapas**: a validação local funcionou, mas esbarrou num
limite físico — com a base no computador do autor, **desligou o PC, morreu a
consulta**. E o momento real de uso é justamente fora de casa, à noite, só com o
celular. Sem consulta na nuvem, o critério da fase não fecha.

**Fase 0a — validação local (feita, em uso):**
- MCP **stdio local**; base **SQLite local**; raspar **na mão, sob demanda** (só
  quando for usar — sem cadência fixa); regras v1 de dedupe + filtro de ruído.
- Validou a raspagem das 3 fontes, o schema unificado, o enriquecimento v1 e a
  conexão com o agente — e revelou a restrição de disponibilidade (seção 5).

**Fase 0b — consulta na nuvem (próximo passo):**
- **Escopo:** migrar a base para **Postgres gerenciado (Neon, free tier)** e expor a
  consulta como **MCP remoto (HTTP)** hospedado em serverless free tier, plugável
  como connector no agente que o autor usa **no celular**. O read-path inteiro passa
  a viver na nuvem.
- **A raspagem continua manual e local:** o `atualizar.py` roda no PC do autor quando
  ele quiser (ex.: 9h de sexta) e faz UPSERT **direto na base remota**. Atualização
  manual não conflita com disponibilidade: o dado das 9h serve o autor às 21h com o
  PC desligado.
- **Portão técnico:** a migração SQLite→Postgres (FTS5 → `tsvector`/`pg_trgm`; o
  `norm_ts` do `consulta.py` migra junto). Antecipado da antiga Fase 1 — retrabalho
  pontual, mas real.
- **Sem** GitHub Actions (automação é Fase 1), **sem** instrumentação de terceiros,
  **sem** porta divulgada: o MCP remoto nasce protegido por segredo/token simples,
  para uso próprio.
- **Critério de sucesso (o da fase):** o autor, **fora de casa e com o computador
  desligado**, pergunta ao agente "o que tem hoje em Brasília" — **e confia na
  resposta em vez de abrir o Sympla**. Dogfooding de um usuário só, o mais exigente.

### Fase 1 — Primeira porta pública (quando a Fase 0 provar valor)

A base hospedada e o MCP remoto **já existem desde a Fase 0b**; a Fase 1 é abrir a
porta para terceiros e tirar o humano da cadência:
- **Escopo:** automatizar a raspagem via **GitHub Actions** (a cadência passa a ser
  **1x/dia**, substituindo o rodar-na-mão); transformar o MCP remoto de segredo de
  uso próprio em **connector instalável por um conhecido** (auth adequada).
- **Instrumentação (parte do escopo):** o MCP remoto precisa **registrar uso**
  (quem/quando consultou, ainda que anonimizado) — sem medição não dá para saber se o
  critério abaixo fechou. Instrumentar é requisito, não enfeite.
- **Critério de sucesso:** **um conhecido** (amigo a quem o autor mostrou o sistema)
  instala o MCP e passa a usar — **e o autor consegue comprovar esse uso pela
  instrumentação**, não por "acho que ele usou".

### Fase 2 — Invisível-first de verdade (superfície achável)

- **Escopo:** páginas públicas por evento e por lista (cidade/gênero/data) com **JSON-LD
  `schema.org/Event`**, `llms.txt` e sitemap, servidas pela camada serverless. Semear
  descoberta (diretórios, `llms.txt` divulgado, links).
- **Instrumentação (parte do escopo):** medir **acesso de terceiros desconhecidos** —
  analytics das páginas públicas e/ou logs do MCP que distingam um uso que não veio do
  autor nem de conhecidos. Sem isso, "um estranho usou" é palpite.
- **Critério de sucesso:** **um estranho** — alguém que o autor não conhece — descobre
  o sistema organicamente (via busca do próprio agente) e usa, **com o acesso
  registrado pela instrumentação**.

### Trilha de dados (dentro do MVP, sequenciada por esforço)

As fases 0/1/2 acima são o **eixo de distribuição** (quem descobre/usa). Em paralelo,
a **cobertura de dados** cresce numa trilha própria, toda dogfoodada pelo autor e
ordenada do mais barato ao mais trabalhoso:

1. **Núcleo — festas/baladas/shows** (Sympla, Ingresse, Shotgun). É o que já existe;
   base da Fase 0.
2. **Cinema** (Cinemark, Kinoplex...): novas fontes, mesmo schema cidade-aware. Subetapa
   separada por adicionar complexidade, mas ainda no MVP.
3. **Instagram + classificação por LLM (última etapa do MVP):** raspar o Instagram da
   festa/casa para suprir a descrição pobre da plataforma de ingressos, e classificar
   gênero/vibe com **Sonnet via subagente** (é aqui que o enriquecimento v2 primeiro
   entra em produção — dogfoodado). A mais trabalhosa, mas **necessária** para o
   raspador ser de fato útil em vida noturna.

### Depois (fora do MVP)

- **Escalar o enriquecimento por LLM** para todo o catálogo com cadência/custo
  gerenciados (o v2 já terá estreado na trilha de dados acima, no recorte de Instagram).
- **Expansão multi-cidade:** acender novas cidades no schema já cidade-aware.
- **Cara própria** para humanos, se provar vantagem.
- Aumento de frescor/cadência conforme o uso crescer.

## 7. Decisões técnicas travadas

- **Distribuição:** híbrido, invisível-first; cara própria opcional.
- **Disponibilidade:** o read-path (base + consulta) vive na nuvem **desde a Fase
  0b** — a consulta não pode depender do computador do autor estar ligado (achado do
  dogfooding de 2026-07-10).
- **Banco:** **SQLite** na Fase 0a; **Postgres no Neon** (free tier) a partir da
  **Fase 0b** (antecipado da Fase 1 pela decisão de disponibilidade acima).
- **Automação de raspagem:** **na mão** nas Fases 0a/0b (na 0b, o `atualizar.py`
  local grava na base remota); **GitHub Actions** a partir da Fase 1 (não antes —
  Actions substitui o "rodar na mão", não o precede).
- **Serve:** serverless gerenciado (read-path), a partir da Fase 0b. Write-path fica
  fora do serverless por causa do Playwright.
- **Cadência:** **sob demanda** nas Fases 0a/0b (atualiza só quando for usar —
  atualização manual e disponibilidade da consulta são eixos independentes); **1x/dia**
  a partir da Fase 1; aumentar conforme o projeto crescer. Prioridade é provar com
  dados reais, não frescor de minuto.
- **Custo:** só **free tier + soluções locais**. Nada de cloud paga nas próximas semanas.
- **Enriquecimento:** faseado — regras na v1; LLM na v2 com **Sonnet** (não Haiku),
  rodado **por subagente no Claude Code CLI** (aproveitando a assinatura), **não por
  API paga**.
- **Escopo:** Brasília-only; **festas/baladas/shows + cinema**; **Instagram** como fonte
  de contexto na última etapa; schema cidade-aware.
- **Medição de uso:** as Fases 1 e 2 só fecham com **instrumentação** que comprove uso
  de terceiros — critério não vale por percepção.

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
  Mitigação: na Fase 0 basta atualizar **sob demanda**; 1x/dia a partir da Fase 1 é
  suficiente para vida noturna.
- **MCP remoto exposto na internet** (a partir da Fase 0b): endpoint público antes de
  o produto ser público. Mitigação: na 0b, segredo/token simples e URL não divulgada
  (só o autor usa); auth de verdade quando abrir a conhecidos (Fase 1).
- **Limites do free tier** (Neon hiberna/limita, serverless com cold start): pode dar
  latência ou indisponibilidade pontual. Aceitável para um usuário na 0b; medir antes
  de prometer a terceiros na Fase 1.
- **Instagram frágil/bloqueado:** é a fonte mais resistente à raspagem (login wall,
  bloqueios, layout volátil). Mitigação: tratar como **última etapa**, com escopo
  mínimo (só o suficiente para inferir o estilo) e tolerância a falha — se um perfil
  não raspar, o evento ainda entra pela plataforma de ingressos.
- **Uso de terceiros não medido:** sem instrumentação, "um conhecido/estranho usou"
  vira achismo e as Fases 1 e 2 nunca fecham de verdade. Mitigação: instrumentação de
  uso é escopo obrigatório dessas fases (seção 6).
- **Legal / Termos de Uso:** raspagem de catálogo público vs. ToS de cada plataforma —
  a avaliar antes de qualquer operação comercial. Vale em dobro para o **Instagram**.

## 9. Não-objetivos (MVP)

- Outras cidades além de Brasília no lançamento.
- Outros tipos de evento além de festas/baladas/shows e cinema.
- App ou site como produto principal (produto é invisível).
- Compra de ingressos, contas de usuário, pagamentos.
- LLM na ingestão **no núcleo inicial** — ele só estreia na última etapa do MVP
  (Instagram/gênero), não no lançamento de festas.
- Automação de raspagem em nuvem nas primeiras semanas (é Fase 1).
- Cobertura 100% garantida do catálogo desde o dia 1.

## 10. Métricas de sucesso

A métrica do MVP **é a escada de anéis** — cada fase só avança quando o anel de dentro
fechou:

- **Fase 0 — eu:** o autor troca o Sympla pelo agente para descobrir a noite de
  Brasília, e confia na resposta — **inclusive fora de casa, com o computador
  desligado** (celular + MCP remoto, Fase 0b).
- **Fase 1 — um conhecido:** um amigo instala o MCP e usa de verdade — **comprovado por
  instrumentação de uso**, não por percepção.
- **Fase 2 — um estranho:** alguém desconhecido descobre organicamente e usa —
  igualmente **medido** (analytics das páginas públicas / logs do MCP que distingam o
  terceiro).

As Fases 1 e 2 exigem, portanto, instrumentação como parte do escopo (seção 6): sem
medir, não há como afirmar que o anel fechou.

Sinais qualitativos de apoio (não são o gatilho de fase): as respostas do agente batem
com o que está realmente à venda (precisão) e cobrem o que deveriam (recall). Quando o
LLM v2 entrar, medir se "festa de pagode" passa a retornar festas de pagode que **não
têm a palavra no nome**.

## 11. Documentos de referência

- `docs/PRD_POC.md` — registro histórico da prova de conceito (validação da raspagem).
- `docs/backlogs/` — backlog priorizado (`nao-iniciado.yaml` + `rejeitado.yaml`).
- `docs/TESTE_MCP.md` — como plugar o MCP nos clientes de IA.
