# Anexo — Onde rodar a raspagem automatizada (§6.1)

> Anexo da spec `20260726_abrir-ao-publico`. Escrito em 2026-07-26 para o autor
> decidir a plataforma do cron antes de cravar GitHub Actions (que é o que o
> PRD §7 presume desde o início, sem ter sido comparado com alternativas).

---

## 1. O problema, dito com precisão

Hoje o `atualizar.py` roda no PC do autor, quando ele lembra. O objetivo é **tirar
o humano da cadência** sem reintroduzir dependência de máquina ligada.

Isso **não** é "rodar uma função na nuvem". O que precisa rodar é um processo com
um perfil bem específico, e é esse perfil que elimina a maior parte das opções.

### 1.1 Requisitos reais (apurados no código e nas execuções)

| Requisito | Valor | De onde vem |
|---|---|---|
| **Duração** | 9,2 min (rodada completa, 17/07) · estimativa 10–15 min com Instagram | tabela `execucoes` |
| **Python** | 3.12+ | `pyproject.toml` |
| **Chromium** | obrigatório | Shotgun bloqueia HTTP puro com 429 |
| **Node.js** | obrigatório | CLI do Monid (`npm i -g @monid-ai/cli`) |
| **Rede de saída** | HTTPS para 7 domínios + Neon | scrapers |
| **Segredos** | `EVENTOS_DB_URL`, chave do Monid | — |
| **Estado entre execuções** | nenhum | a base é o estado; o processo é stateless |
| **Frequência** | 1x/dia | PRD §7 |

O ponto que decide quase tudo: **é um processo de ~10–15 minutos que precisa de
Python + Node + um navegador de verdade**. Isso é um container, não uma function.

### 1.2 O que NÃO precisa rodar lá

Pelo caminho 1 já decidido (§3 passo 2 da spec), a **extração de flyer por visão**
(`claude -p` na assinatura) fica fora do cron e continua manual. Isso simplifica o
ambiente: nada de autenticação de assinatura, nada de sessão interativa.

---

## 2. As opções

### A — GitHub Actions *(recomendada)*

Workflow com `schedule`, rodando no runner `ubuntu-latest`.

- **Custo: R$ 0, sem teto prático.** O repositório é **público**
  (`github.com/oextraordimario/raspador_eventos`), e repositório público tem
  minutos de Actions **gratuitos e ilimitados**. Isso não vale para repo privado
  (2.000 min/mês no free) — se o repo algum dia fechar, a conta muda: ~15 min/dia
  ≈ 450 min/mês, ainda dentro do free, mas com teto.
- **Ambiente:** o runner Ubuntu já vem com Python e Node instalados. Falta só
  `pip install -r requirements.txt` + `playwright install chromium` (~1–2 min de
  overhead por execução, cacheável).
- **Limite de duração:** 6 horas por job. Folga de 24× sobre o necessário.
- **Segredos:** nativos (`Settings → Secrets`), sem infra extra.
- **Operação:** log por execução na aba Actions, re-run manual com um clique,
  `workflow_dispatch` para disparar na mão quando quiser.
- **Já é o que o PRD §7 assume.**

**As duas ressalvas honestas — e são reais:**

1. **O cron do Actions é *best effort*, não pontual.** Em horários de pico a fila
   pode atrasar o disparo em 10–30+ minutos. Para uma raspagem diária de vida
   noturna isso é irrelevante; para "quero exatamente às 6h", não serve.
2. **O GitHub desabilita workflows agendados em repositório sem atividade por 60
   dias.** Manda e-mail antes e basta um clique (ou um commit) para reativar, mas
   é uma armadilha real em projeto pessoal que fica um tempo parado — justamente
   quando você mais confia que "está rodando sozinho". Mitigação: qualquer commit
   no período zera o contador; um lembrete no calendário resolve o resto.

### B — Google Cloud Run Jobs

Container próprio, disparado por Cloud Scheduler.

- **Custo:** free tier generoso (Cloud Run cobra por execução/CPU; ~15 min/dia
  fica dentro ou muito perto de zero). Artifact Registry tem custo pequeno de
  storage da imagem.
- **Ambiente:** Dockerfile próprio — você controla Python, Node e Chromium
  exatamente. Sem surpresa de mudança de runner.
- **Limite de duração:** até 24 h. Sem preocupação nenhuma.
- **Pontualidade:** Cloud Scheduler dispara no horário, de verdade.
- **Custo real da opção:** setup. Dockerfile, build, push para registry, IAM,
  Secret Manager, Scheduler. É a diferença entre um arquivo YAML no repo e uma
  conta de nuvem para administrar — e o PRD §5 escolheu Actions justamente com o
  argumento de "sem VPS para cuidar". Cloud Run não é VPS, mas é infra.
- **Quando vale:** se a pontualidade importar, se o processo crescer muito, ou se
  o repo virar privado e os minutos passarem a contar.

### C — AWS Lambda

- **Não recomendo, e o motivo é numérico:** o teto de execução do Lambda é **15
  minutos**. A rodada completa já leva 9,2 min hoje e a estimativa com Instagram
  é 10–15 min. Você começaria com a margem quase toda consumida, e o catálogo só
  cresce (o Sympla já traz 380 eventos). Estourar o teto significa rodada cortada
  no meio — e, pior, cortada de forma silenciosa e parcial.
- Somado a isso: Chromium em Lambda exige imagem de container ou layer específica
  (`@sparticuz/chromium` e afins), o que é mais atrito do que o Cloud Run pelo
  mesmo trabalho. **Se for para container em nuvem, Cloud Run Jobs é o encaixe
  melhor.**

### D — Vercel Cron

- **Não serve.** O cron da Vercel dispara uma Function, e Function tem teto de
  execução muito abaixo dos 10–15 min necessários (o `vercel.json` do projeto usa
  `maxDuration: 60`). Dividir a rodada em N funções encadeadas para caber
  transformaria um script linear em uma máquina de estados distribuída — é
  complexidade nova pura, sem ganho.
- **Vale registrar por outro motivo:** é tentador porque o projeto já está na
  Vercel. Não confundir a porta de leitura (serverless, escala a zero, perfeita)
  com o write-path (processo longo com navegador). O PRD §5 já separa os dois.

### E — Fly.io / Render / Railway (cron de container)

- Meio-termo entre Actions e Cloud Run: container, mas com menos cerimônia que a
  GCP. Render tem cron jobs; Fly tem `fly machine run` agendado.
- **O problema é custo:** cron job no Render é recurso pago; o free tier do Fly é
  limitado e a política mudou nos últimos anos. Sai do "só free tier" que o PRD §7
  trava, para resolver um problema que o Actions resolve de graça.

### F — VPS + crontab

- Controle total, previsível, ~US$ 4–5/mês.
- **Explicitamente rejeitado pelo PRD §5** ("sem VPS para cuidar"). Reintroduz
  patch, segurança e disco para administrar — o oposto do que a Fase 0b buscou.

### G — Continuar local, mas agendado (Agendador de Tarefas do Windows)

- Custo zero e ambiente já pronto — hoje já funciona nessa máquina.
- **Mas reintroduz exatamente a dependência que a Fase 0b eliminou:** PC ligado.
  O achado do dogfooding de 2026-07-10 foi que o read-path não podia depender
  disso; se o write-path depender, a base envelhece toda vez que você viajar.
- **Único caso em que faz sentido:** rodar a **extração de flyer** (que fica fora
  do cron pelo caminho 1) de forma agendada quando a máquina estiver ligada, como
  complemento — não como substituto.

---

## 3. Comparativo

| | Custo | Cabe em 15 min? | Python+Node+Chromium | Pontual | Setup | Infra p/ cuidar |
|---|---|---|---|---|---|---|
| **A** GitHub Actions | R$ 0 (repo público) | sim (teto 6 h) | runner já tem | não (best effort) | 1 arquivo YAML | nenhuma |
| **B** Cloud Run Jobs | ~R$ 0 (free tier) | sim (teto 24 h) | Dockerfile próprio | sim | médio | conta GCP |
| **C** AWS Lambda | ~R$ 0 | **teto 15 min — apertado** | layer/imagem p/ Chromium | sim | médio-alto | conta AWS |
| **D** Vercel Cron | R$ 0 | **não** | não | sim | — | — |
| **E** Fly/Render/Railway | **pago** | sim | container | sim | baixo-médio | conta |
| **F** VPS + crontab | ~US$ 5/mês | sim | você instala | sim | alto | **sim** |
| **G** Local agendado | R$ 0 | sim | já pronto | só com PC ligado | mínimo | nenhuma |

## 4. Recomendação

**A — GitHub Actions**, e a razão principal mudou de "é o que o PRD disse" para
um fato verificado hoje: **o repositório é público, então os minutos são
gratuitos e ilimitados**. Some a isso que o runner já traz Python e Node, que o
teto de 6 h dá folga de 24× sobre a necessidade real, e que o setup é um arquivo
YAML versionado junto do código que ele executa — sem conta de nuvem nova, sem
imagem para buildar, sem IAM.

As duas ressalvas (atraso no disparo, desativação após 60 dias de inatividade)
são reais, mas nenhuma delas machuca este caso: raspagem diária de vida noturna
não precisa de pontualidade ao minuto, e o repo está em desenvolvimento ativo.

**O gatilho para reavaliar em favor do B (Cloud Run Jobs):** o repo virar privado,
a rodada passar de ~30 min, ou a pontualidade do horário passar a importar de
verdade.

**Sobre o horário** (a outra metade da §6.1): o trade-off é entre frescor do
catálogo e maturidade do lote. Rodar de madrugada entrega a noite do mesmo dia
com o dado mais completo do dia anterior; rodar no fim da tarde tem o lote de
ingresso mais maduro, mas deixa o dia inteiro servindo a coleta da véspera. Como
o cron do Actions atrasa de todo jeito, sugiro **início da madrugada, horário de
Brasília** (ex.: `0 6 * * *` em UTC = 3h em Brasília): a fila do GitHub é mais
curta fora do pico americano, e a base fica pronta antes de qualquer pessoa
acordar e perguntar o que tem hoje.
