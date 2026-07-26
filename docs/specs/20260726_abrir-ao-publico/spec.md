# Spec — Abrir o sistema ao público: cron, site e onboarding (NI-10 + NI-11 + NI-21 + NI-28)

> **Status: APROVADA e IMPLEMENTADA em 2026-07-26** — as oito questões foram
> decididas pelo autor no mesmo dia (§6 tem o mapa) e os cinco passos estão no
> código e no ar.
>
> **O que está pronto e validado:**
> - **Passo 1** — `LICENSE` (MIT, ZeroUm Soluções em Dados) e `README.md`.
> - **Passo 2** — `.github/workflows/raspar.yml` (06:00 UTC = 3h BRT) + as
>   flags `--sem-extracao-flyer` e `--so-instagram`, que o caminho 1 exigia e
>   não existiam. Secrets `EVENTOS_DB_URL` e `MONID_KEY` gravados no GitHub.
> - **Passo 3** — `api/dados.py` (API de leitura, 21 checagens em
>   `tests/test_api_dados.py`) e o front em `app/`/`lib/`. Roteamento do
>   `vercel.json` refeito sem derrubar o MCP.
> - **Passo 5** — JSON-LD por evento, `sitemap.xml`, `robots.txt`, `llms.txt`.
> - **Passo 4** — tabelas `usuarios`/`acessos` + decorator `@registrado` nas 5
>   tools (a instrumentação já media antes do login, com `sub` NULL) e, desde a
>   conta WorkOS ficar de pé no mesmo dia, o OAuth completo: `src/auth.py`
>   verifica o JWT contra o JWKS do AuthKit, o FastMCP publica
>   `/.well-known/oauth-protected-resource/mcp` e o connector passou a viver em
>   **`https://raspador-eventos.vercel.app/mcp`** — URL pública, protegida por
>   login e não mais por sigilo de endereço.
>
> **Ressalvas do passo 4:**
> - O issuer aponta para o **Staging** do WorkOS; o Production está configurado
>   igual e a troca é uma env (`AUTHKIT_ISSUER`), mas exige ativar Production no
>   painel. Ao trocar, todo mundo re-autentica — `sub` é por ambiente.
> - `MCP_SEGREDO` **não morreu ainda**: a rewrite `/:segredo/mcp` segue no
>   `vercel.json` para o rollback ser troca de env. Sai quando o fluxo tiver
>   rodado com gente de verdade.
> - A "landing com o passo a passo" prevista na spec do NI-11 virou a página
>   `/sobre` do site, como a nota de integração deste passo antecipava.
>
> **O que falta para divulgar:** a decisão travada em §4 exige o **cron rodando
> antes** — o workflow está no ar mas ainda não disparou nenhuma vez.
>
> **O quê/por quê:** o gatilho não é técnico, é de demanda. O autor mostrou o
> sistema a conhecidos e passou a ser cobrado — *"quero usar isso, põe pra jogo"*.
> Hoje não existe nenhuma porta que uma dessas pessoas consiga atravessar: a
> consulta exige ser um agente de IA falando MCP, e o acesso é um prefixo de rota
> secreto de uso pessoal. Esta spec reúne, num plano só, o que falta para um
> terceiro usar o sistema sem falar com o autor.
>
> **Relação com o PRD:** fecha a cláusula condicional do PRD §4 ("cara própria só
> entra se provar vantagem") — a demanda espontânea É a evidência que aquela
> cláusula pedia. Cobre o eixo de distribuição da **Fase 1** (anel "um conhecido")
> e antecipa parte da **Fase 2** (superfície achável). O PRD §9 lista "app ou site
> como produto principal" nos não-objetivos: esta spec **não** contradiz isso — o
> site é uma segunda porta sobre a mesma base, não o produto principal. Se
> aprovada, o PRD §4/§9 precisa de uma nota registrando a decisão (§8).
>
> **Contexto de infra:** nenhuma mudança destrutiva de schema. O passo 4 cria
> `usuarios` e `acessos` via `CREATE TABLE IF NOT EXISTS` — **não precisa
> descartar a base**.

---

## 1. Estado atual — o diagnóstico que motivou a spec

Levantado em 2026-07-26, contra a base de produção.

### 1.1 A base está velha, e ninguém vê isso

Última coleta por fonte (`select fonte, max(raspado_em) from eventos group by fonte`):

| Fonte | Última coleta | Idade | Eventos |
|---|---|---|---|
| sympla | 23/07 14:52 UTC | 3 dias | 380 |
| ticketandgo | 23/07 14:52 UTC | 3 dias | 110 |
| instagram | 23/07 14:56 UTC | 3 dias | 53 |
| ingresse | 23/07 14:52 UTC | 3 dias | 6 |
| zig | 23/07 14:52 UTC | 3 dias | 4 |
| **shotgun** | **17/07 11:00 UTC** | **9 dias** | **77** |

Em 10 rodadas registradas em `execucoes`, **uma única** foi `modo='completo'`
(id 6, 17/07) — todas as outras foram `sem-shotgun`, porque o Playwright é lento.
Consequência: os 77 eventos do Shotgun são servidos como atuais sem terem sido
verificados há 9 dias, e o `_marcar_sumidos` não roda para eles (por desenho: só
marca sumido em fonte raspada sem erro). Um evento do Shotgun cancelado há uma
semana continua aparecendo na busca.

Enquanto o único usuário é o autor, isso é inofensivo — ele sabe quando rodou.
Para um terceiro, é **resposta errada com cara de resposta certa**, que é o pior
modo de falha possível para este produto.

### 1.2 Não há porta de entrada humana no repo

- **Não existe `README.md` na raiz.** A única documentação que um visitante
  encontra é o `CLAUDE.md`, escrito para o agente, não para gente.
- **Não existe `LICENSE`** (NI-21). O repo está público desde 2026-07-11; sem
  licença, o padrão legal é "todos os direitos reservados" — ninguém pode
  legalmente usar, copiar ou modificar o código.

### 1.3 O acesso não distingue pessoas

O MCP remoto (NI-20) autoriza por prefixo de rota secreto (`MCP_SEGREDO`). Ele
não identifica quem consulta, não se revoga individualmente e não registra nada.
Distribuir esse link é distribuir a mesma chave para todos e ficar cego quanto ao
uso — e o critério da Fase 1 (PRD §10) não fecha sem registro de uso.

### 1.4 A única interface é um agente de IA

Não há superfície visual. O público que está cobrando o autor não quer instalar
connector — quer abrir um link e clicar.

---

## 2. Arquitetura das mudanças

O sistema tem três camadas. Cada passo desta spec mexe em **exatamente uma**:

```
  WRITE ─── atualizar.py ─────────── hoje: PC do autor, na mão
    │                                [2] passa a ser GitHub Actions (1x/dia)
    ▼
  BASE ──── Postgres no Neon ─────── não muda
    │                                ([4] acrescenta usuarios + acessos)
    ▼
  READ ──── consulta.py ──────────── PONTO ÚNICO — não muda em nenhum passo
    │
    ├── api/index.py ─── MCP remoto ──── [4] segredo → OAuth + instrumentação
    └── api/site.py ──── API de leitura ─ [3] NOVA: expõe consulta.py em HTTP
          │                               (exigida pela escolha do Next.js)
          ▼
        front Next.js ── site HTML ────── [3] cria · [5] marca em JSON-LD
```

**A `consulta.py` é o que torna esta lista barata.** Ela já é a camada canônica:
dedupe, filtro de ruído, `cancelado`, `sumido`, FTS e `outras_urls` vivem lá.
Nenhum passo reimplementa isso.

**Consequência da escolha do Next.js (§4):** o front é JavaScript e a camada
canônica é Python, então o site **não pode** chamar `consulta.py` como chamada de
função — precisa de uma **API HTTP fina** em Python entre os dois (`api/site.py`,
nova). Essa API não tem lógica própria: traduz querystring em argumentos de
`buscar_eventos`/`detalhar_evento`/`buscar_filmes`/`sessoes_filme` e devolve o JSON
que elas já retornam. É o mesmo papel que o `mcp_server.py` faz para a porta MCP.

**Alternativa rejeitada:** o Next ler o Neon direto (via driver JS). Cortaria a
API, mas duplicaria em JavaScript as regras de dedupe, ruído, `sumido` e FTS que
hoje vivem em um lugar só — e as duas cópias divergiriam na primeira mudança de
regra. Não fazer, mesmo que pareça mais curto.

**Custo assumido da escolha:** dois runtimes (Node + Python) e dois artefatos de
deploy no mesmo projeto Vercel, contra um só na alternativa de servir HTML pelo
Python. O ganho é acabamento de front e ecossistema (shadcn/Tailwind, componentes,
SSR pronto para o passo 5). Decisão do autor em 2026-07-26.

### 2.1 Dependências reais

Só existem duas, e nenhuma é técnica:

- **[2] trava [3], [4] e [5]** — por produto, não por engenharia. Qualquer porta
  nova serve dado velho enquanto a raspagem depender de o autor lembrar. Já
  travado na spec do NI-11 §10 ("cron antes de divulgar").
- **[3] trava [5]** — o passo 5 é literalmente marcar as páginas do passo 3.

**[1] não depende de nada** e pode ser feito em paralelo, hoje.
**[3] e [4] são independentes entre si** — duas portas distintas sobre a mesma
base. A ordem entre elas é escolha de público, não de engenharia.

---

## 3. Os passos

### Passo 1 — LICENSE + README (NI-21 + NI-28)

**Escopo:**
- `LICENSE` na raiz — **MIT** (decidido pelo autor em 2026-07-26). Arquivo sem
  extensão, texto integral da licença, com `[year]` = 2026 e `[fullname]` = o nome
  do autor; o GitHub detecta e exibe na sidebar. Template em
  https://choosealicense.com/licenses/mit/.
- `README.md` na raiz, para humanos, com: o que é o sistema em 3 linhas, o que ele
  cobre (Brasília, vida noturna + cinema), como usar (link do site e/ou do
  connector), e — separado, no fim — como rodar localmente.
- O `README` **não** substitui o `CLAUDE.md`; são públicos diferentes.

**Nota do NI-21:** a licença cobre o CÓDIGO. Os payloads raspados das plataformas
não são nossos para licenciar e não precisam de cláusula especial.

### Passo 2 — Cron da raspagem (NI-10)

**Escopo:** GitHub Actions agendado, 1x/dia, rodando o `atualizar.py` **completo**
(inclusive Shotgun — é justamente o que está 9 dias atrasado) com UPSERT direto na
base remota. Substitui o rodar-na-mão; não o precede.

**Plataforma: GitHub Actions** — decidida pelo autor em 2026-07-26 após o
comparativo de sete opções no anexo `cron.md`. O que sustenta: o repositório é
**público**, então os minutos são gratuitos e ilimitados; o runner Ubuntu já traz
Python e Node; o teto de 6 h dá folga de 24× sobre os 10–15 min necessários; e o
setup é um YAML versionado junto do código que ele executa, sem conta de nuvem
nova.

**Horário:** início da madrugada de Brasília (`0 6 * * *` em UTC = 3h local). A
fila do GitHub é mais curta fora do pico americano, e a base fica pronta antes de
alguém acordar e perguntar o que tem hoje.

**Duas ressalvas conhecidas e aceitas:**
- O cron do Actions é *best effort* — em pico, o disparo atrasa 10–30+ min.
  Irrelevante para raspagem diária de vida noturna.
- **O GitHub desabilita workflow agendado em repo sem atividade por 60 dias.**
  Manda e-mail antes e reativa com um clique; qualquer commit zera o contador. É
  a armadilha real desta escolha — vigiar em período de projeto parado.

**PLANO B: Google Cloud Run Jobs** (detalhado no anexo `cron.md` §2.B). Não é
para agora; é o destino já escolhido caso um destes gatilhos dispare:
- o repositório virar **privado** (os minutos passam a ter teto);
- a rodada passar de **~30 min** (hoje são 10–15, e o catálogo cresce);
- a **pontualidade do horário** passar a importar de verdade;
- o workflow ser desabilitado por inatividade **mais de uma vez** — sinal de que
  o modelo não combina com o ritmo do projeto.

Migrar significa empacotar o mesmo `atualizar.py` num Dockerfile (Python + Node +
Chromium) e trocar o gatilho por Cloud Scheduler. O código do pipeline não muda —
por isso o plano B é barato de acionar e não precisa ser preparado agora.

**O que o runner precisa:**
- `pip install -r requirements.txt` + `python -m playwright install chromium`
- secrets: `EVENTOS_DB_URL` (URL pooled do Neon), chave do Monid
- tolerância a falha por fonte já existe no `atualizar.py`; `execucoes` já grava
  erro por evento e o relatório já alerta queda > 50%

**A raspagem não é uma coisa só** — são duas metades com requisitos de execução
diferentes:

```
5 fontes de ingresso + cinema  →  HTTP puro (+ Chromium no Shotgun)
                                  roda em Actions sem problema

Instagram — posts via Monid    →  chave em secret, roda em Actions
Instagram — extração do flyer  →  `claude -p` na ASSINATURA  ← NÃO roda em CI
```

`src/scrapers/instagram.py:286-287` remove `ANTHROPIC_API_KEY` e
`ANTHROPIC_AUTH_TOKEN` do ambiente do subprocesso **de propósito** (decisão do PRD
§7: assinatura, não API paga). Em GitHub Actions não existe login de assinatura.

**DECISÃO TRAVADA pelo autor (2026-07-26): caminho 1.** O cron cobre tudo menos a
extração do flyer por visão. O Instagram continua entrando na Bronze pelo cron
(posts e stories via Monid); só a leitura do flyer fica pendurada até o autor
rodar `atualizar.py` localmente. O passo de extração já é incremental e
re-tentável por desenho (nunca re-extrai shortcode que já tem origem `extracao`
na Bronze), então acumular pendência entre rodadas manuais é seguro.

**Consequência aceita:** eventos que existem *exclusivamente* no Instagram e cujo
flyer ainda não foi lido não aparecem até o autor rodar a extração. Alternativas
descartadas por ora: API paga no CI (contraria PRD §7 — reavaliar com número de
custo real na mão) e runner self-hosted (reintroduz a dependência do PC ligado,
que é exatamente o que a Fase 0b eliminou).

**Custo novo:** o Monid passa a rodar diariamente. Watchlist atual = 6 perfis ×
~$0,006/perfil/rodada ≈ **$0,04/dia ≈ $1,10/mês**. Dentro da exceção já aprovada
ao free-tier-only (NI-06), mas passa de custo eventual a recorrente — registrar.

### Passo 3 — Site público de leitura (NI-28, novo)

**Escopo:** site público de leitura, sem login, sem conta, sem instalação.

**Nome:** `role.bsb` — **provisório**, decidido pelo autor em 2026-07-26 para
destravar o trabalho. O autor registrou que, se o projeto ficar sério, o nome
definitivo será repensado. Implicação prática: **não espalhar o nome** por
constantes, títulos, textos e assets a ponto de renomear virar refatoração. Manter
o nome e o domínio em UM lugar (config/env), consumido por todo o resto.

**Stack: Next.js** (decidido pelo autor em 2026-07-26; App Router, deploy na
Vercel). Consome a API de leitura em Python descrita na §2 — o front não fala com
o Postgres direto. Visual segue o ZeroUm Design System, que já é a origem dos
tokens; Fira Code e Space Grotesk vêm do Google Fonts normalmente (a restrição que
obrigou a embutir as fontes no protótipo era do CSP do artifact).

**Telas** (validadas no protótipo de 2026-07-26 — ver §4):
- **lista** — busca por texto, filtros de período (hoje / fim de semana / 7 dias),
  alternância festas↔cinema, filtro "só grátis"; agrupada por dia local de
  Brasília; card com hora, nome, casa, bairro, preço mínimo, selos (grátis,
  cortesia, esgotado, em alta) e fonte.
- **detalhe do evento** — descrição em **TRECHO + link** (ver postura de ToS
  abaixo), tabela de lotes com o nome CRU da fonte (a condição do lote fica no
  nome, de propósito), link para a plataforma que vende, e `outras_urls` quando o
  evento existe em mais de uma.
- **filmes** — agregado por filme, com cinemas e contagem de sessões.
- **procedência** — última coleta por fonte. Enquanto a raspagem não for
  diária/confiável, a idade do dado é informação que o usuário precisa ver.
- **sobre** — o que o site é, de onde vem o dado, que não vendemos ingresso e
  como uma casa ou plataforma pede remoção. Decorre da postura de ToS.
- **alternância de tema** claro/escuro (o ZeroUm é dark-first e traz os dois).

**Postura sobre ToS: AGREGADOR COM ATRIBUIÇÃO (opção A)** — decidida pelo autor
em 2026-07-26; análise completa no anexo `tos.md`. O site exibe o **fato** (nome,
data, local, preço, disponibilidade) sempre com a fonte visível e o link para
comprar na plataforma de origem. Três medidas que decorrem dela e são escopo
desta spec:
1. **Descrição em trecho + link**, não integral. Hoje o `detalhar_evento`
   (`consulta.py:101`) devolve a descrição INTEIRA — a tool MCP pode continuar
   assim (serve um agente em contexto privado), mas a **página pública, não**:
   descrição é texto autoral do organizador, e reproduzi-la integralmente numa
   página indexada é o ponto mais frágil do sistema. A API de leitura do site
   trunca; o resto fica atrás do "ver no Sympla".
2. **Fonte sempre visível** com link direto de compra — já está no protótipo.
3. **Página "sobre"** (acima), que torna a postura verificável por quem chegar
   reclamando.

Medida conservadora adicional, sem custo de produto: **não exibir `organizador`
quando for nome de pessoa física** (a base tem casos, ex.: "Fernando Chaves"). É
o único campo com cara de dado pessoal na superfície pública (LGPD).

**Imagens: FORA do v1** (decidido pelo autor em 2026-07-26, revendo a decisão de
hotlink tomada mais cedo no mesmo dia). O site nasce **sem capa de evento** — a
lista é puramente tipográfica, como no protótipo aprovado, que demonstrou
funcionar bem assim. A coluna `imagem` continua sendo gravada na base; só não é
consumida pelo front. Ver §9 para o registro do que já foi levantado sobre o
tema, para quando ele voltar.

**Motivo da revisão:** a apuração do hotlink revelou que evento
`fonte='instagram'` **não tem capa** — a coluna é NULA por decisão de arquitetura
(a URL do CDN do Insta expira em horas e nunca é gravada). São justamente os
eventos do Culto e do Ordinário, que só existem lá. Ter capa em parte do catálogo
e não em outra exige desenhar o vazio antes de desenhar a imagem; sem imagem
nenhuma, o problema não existe.

**Ganho colateral:** simplifica a §6.3 (ToS) — sem hotlink, o site serve apenas
dado factual e não passa a servir o *asset* hospedado pela plataforma de origem.

**Ponto de atenção no roteamento:** o `vercel.json` hoje reescreve **todas** as
rotas para `api/index` (o MCP). Com o Next assumindo o domínio, esse catch-all
sai e o roteamento passa a ser: o Next serve as páginas, e as funções Python
(`api/index.py` do MCP, `api/site.py` da leitura) ficam em rotas próprias. É onde
dá para derrubar o MCP sem querer — e o passo 4 mexe no mesmo arquivo. Fazer os
dois com o roteamento desenhado de uma vez, não em dois sustos.

#### Instrumentação — PostHog

**Decidido pelo autor em 2026-07-26.** O autor já usa e gosta da ferramenta, e
tem um projeto antigo (de produto descontinuado) que pode ser reaproveitado para
este. Quatro razões que sustentam a escolha além da familiaridade:

1. **Responde a pergunta certa.** O critério das Fases 1 e 2 (PRD §10) não é
   "quantos pageviews" — é *"um conhecido/estranho **usa** de verdade"*. Isso é
   retenção e recorrência, que é product analytics, não analytics de aquisição.
2. **Unifica as duas portas.** O PostHog ingere evento de backend (SDK Python /
   API). O passo 4 vai gravar acessos ao MCP na tabela `acessos`; esses mesmos
   acessos podem ser espelhados como evento no PostHog, com o `distinct_id` vindo
   do login OAuth. Resultado: **uma medição só** cobrindo site e MCP, em vez de
   dois painéis que não conversam. Nenhuma alternativa faz isso bem.
3. **Free tier folgado:** 1M eventos/mês, muito acima de qualquer projeção
   realista aqui.
4. **Privacidade tratável:** roda sem cookie e com host na UE, o que simplifica a
   conversa de LGPD numa página pública.

**Alternativas consideradas e por que não:**
- **Google Analytics 4** — feito para marketing e aquisição, não para responder
  "a pessoa voltou na semana seguinte?". Além disso é o alvo nº 1 de adblocker,
  e o público deste produto (vida noturna, majoritariamente jovem e mobile) é
  justamente o que mais bloqueia — a subcontagem cairia exatamente sobre quem a
  gente precisa medir. E não recebe evento de servidor com naturalidade, o que
  mataria a unificação com o MCP.
- **Plausible / Umami / Fathom / Vercel Analytics** — leves, privacy-first e
  bonitos, mas entregam pageview e pouco mais. Não respondem retenção nem
  unificam com a porta MCP.

**Ponto de atenção herdado:** adblocker também bloqueia o PostHog. Mitigação
conhecida e barata no Next: servir a ingestão por **proxy reverso no próprio
domínio** (rewrite no `next.config`), em vez de bater no host do PostHog direto.
Fazer isso desde o início — retrofitar depois invalida a série histórica.

**Nota de escopo:** instrumentar o **site** é escopo desta spec; instrumentar o
**MCP** é escopo do NI-11. A decisão de plataforma aqui vincula os dois, para que
não nasçam medições concorrentes.

### Passo 4 — OAuth + instrumentação no MCP (NI-11)

**Escopo:** já especificado em detalhe em `docs/specs/20260714_abrir-mcp-a-conhecidos/`
(spec APROVADA em 2026-07-14, implementação não iniciada). **Esta spec não
redesenha aquilo** — apenas o posiciona na sequência. Resumo do que está travado
lá: URL do connector vira pública, controle passa para o login (OAuth com DCR,
AuthKit da WorkOS como servidor de autorização), tabelas `usuarios` + `acessos`,
landing com o passo a passo, `MCP_SEGREDO` morre. Acesso aberto a quem logar, sem
allowlist; controle reativo por teto + bloqueio.

**Nota de integração:** aquela spec previa uma "landing page estática com o passo
a passo". Se o passo 3 for feito antes, a landing deixa de ser página solta e vira
uma seção do site. Vale um alinhamento entre as duas specs no momento da
implementação — não é conflito, é economia.

**Como ficou (2026-07-26).** O AuthKit é só *authorization server*; nada de
credencial nossa em lugar nenhum. Três achados que valem registro, porque não
estavam previstos:

1. **`mcp>=1.28` é piso duro.** O `pyproject.toml` pedia `>=1.10`, então a
   Vercel já instalava a mais nova enquanto o dev local tinha 1.10.1 — dois
   ambientes com APIs de auth diferentes e nenhum erro visível. Só a partir da
   1.28 o `AccessToken` carrega `claims`/`subject` e a rota de metadados segue
   a RFC 9728 (`/.well-known/oauth-protected-resource/mcp`); na 1.10 o SDK
   registrava a rota na raiz e anunciava outra, e o cliente nunca fecharia o
   fluxo. Piso frouxo em dependência que define contrato de rede é armadilha.
2. **A rewrite da descoberta é tão crítica quanto a do endpoint.** Sem
   `/.well-known/oauth-protected-resource/:recurso*` no `vercel.json`, o Next
   responde 404 no lugar do metadado e o cliente leva o 401 sem saber onde
   autenticar — falha muda, que parece "login não funciona".
3. **Ligar por env, não por flag.** `AUTHKIT_ISSUER` + `MCP_RECURSO` presentes
   = auth; ausentes = modo antigo. O mesmo módulo serve stdio local e remoto, e
   o rollback não passa por código.

### Passo 5 — Superfície achável (Fase 2)

**Escopo:** JSON-LD `schema.org/Event` nas páginas do passo 3, `llms.txt` e
sitemap. É o invisível-first na forma pura: o agente de qualquer pessoa acha o
conteúdo pela busca web, sem instalar nada.

**Expectativa calibrada:** o PRD §4 já registra o risco de cold-start — domínio
novo não ranqueia para "festas em Brasília hoje" tão cedo. Este passo é jogo
longo; não é ele que fecha a Fase 1.

---

## 4. Decisões já travadas (não rediscutir sem fato novo)

| Decisão | Quando | Origem |
|---|---|---|
| Público-alvo é quem **só usa**, sem instalar nada | 2026-07-26 | autor |
| Interface é **busca com filtros e botões**, não chat | 2026-07-26 | autor — chat teria custo de LLM por pergunta, por usuário |
| UX do protótipo aprovada como está | 2026-07-26 | autor |
| Visual segue o **ZeroUm Design System** | 2026-07-26 | autor |
| Instagram no cron: **caminho 1** (sem extração de flyer em CI) | 2026-07-26 | autor — §3 passo 2 |
| Licença **MIT** | 2026-07-26 | autor — §3 passo 1 |
| Stack do site: **Next.js** + API de leitura em Python | 2026-07-26 | autor — §2 e §3 passo 3 |
| Nome **`role.bsb`**, provisório e isolado em config | 2026-07-26 | autor — §3 passo 3 |
| **Sem imagens** no v1 do site (adiado, não descartado) | 2026-07-26 | autor — §3 passo 3 e §9 |
| Postura de ToS: **agregador com atribuição** (opção A) | 2026-07-26 | autor — anexo `tos.md` |
| Descrição em **trecho + link** na página pública (MCP segue integral) | 2026-07-26 | decorre da postura A |
| Instrumentação: **PostHog**, cobrindo site e MCP | 2026-07-26 | autor — §3 passo 3 |
| Cron no **GitHub Actions**, 3h de Brasília; **Cloud Run Jobs como plano B** | 2026-07-26 | autor — §3 passo 2 e anexo `cron.md` |
| Cron **antes** de divulgar o link | 2026-07-14 | spec NI-11 §10 |
| Acesso ao MCP aberto a quem logar, sem allowlist | 2026-07-14 | spec NI-11 |

**Protótipo de referência:** construído em 2026-07-26 com dados reais da base
(snapshot de 26/07 10h41 UTC), incluindo os lotes verdadeiros da MOLHADÊRA do CPX.
Publicado como artifact; UX e visual aprovados pelo autor. Serve de referência
visual para o passo 3, não como código a reaproveitar (é HTML estático com dados
congelados).

**Nota sobre as fontes do ZeroUm:** o `colors_and_type.css` do design system puxa
Fira Code e Space Grotesk do Google Fonts por `@import`. No site próprio isso
funciona normalmente (a restrição que obrigou a embutir as fontes no protótipo era
do CSP do artifact, não do design system).

---

## 5. Plano de validação (autoexecutável)

Cada passo entrega com validação que roda sozinha, sem roteiro manual — padrão
adotado desde a spec do Instagram.

- **Passo 1:** conferência visual no GitHub (licença detectada na sidebar).
  Sem teste automatizado — é conteúdo, não código.
- **Passo 2:** primeira execução agendada grava linha em `execucoes` com
  `modo='completo'` e `fontes.shotgun.coletados > 0`; relatório sem alerta de
  queda > 50%. Teste de regressão: `select max(raspado_em) from eventos group by
  fonte` com todas as fontes dentro de 48h.
- **Passo 3:** a stack partida em dois exige validação em dois níveis.
  - **API de leitura (Python):** teste de fumaça novo `tests/test_site_api.py`, no
    padrão dos demais (script executável, sem framework), contra o banco
    `eventos_teste`: lista responde 200 com N eventos, detalhe de um evento
    conhecido traz os lotes, filtro de período recorta, busca textual acha por
    descrição. É aqui que mora a corretude — a API é a fronteira da camada
    canônica.
  - **Front (Next.js):** o repo não tem runner de teste JS e esta spec **não**
    introduz um. Validação por checagem de renderização com Playwright, que já é
    dependência do projeto: subir o build, abrir lista e detalhe, afirmar que os
    eventos aparecem, que evento sem preço e sem lote (caso comum em
    `fonte='instagram'`) renderiza sem buraco no card, e que os dois temas
    renderizam legíveis.
- **Passo 4:** o plano de teste está na spec do NI-11.
- **Passo 5:** validador de rich results do Google + leitura do `llms.txt`.

---

## 6. QUESTÕES ABERTAS

**Nenhuma.** As oito questões levantadas em 2026-07-26 foram todas decididas pelo
autor no mesmo dia e migraram para a §4 (decisões travadas) e para o corpo dos
passos:

| Questão original | Onde foi parar |
|---|---|
| Licença | MIT — §3 passo 1 |
| Stack do site | Next.js + API de leitura em Python — §2 e §3 passo 3 |
| Nome e domínio | `role.bsb` provisório, isolado em config — §3 passo 3 |
| Imagens dos eventos | fora do v1, adiadas — §3 passo 3 e §9 |
| Vercel Hobby | risco registrado com gatilho — §7 |
| Horário/plataforma do cron | Actions às 3h BRT, Cloud Run como plano B — §3 passo 2 e anexo `cron.md` |
| Instrumentação do site | PostHog, cobrindo as duas portas — §3 passo 3 |
| Postura sobre ToS | agregador com atribuição (A) — §3 passo 3 e anexo `tos.md` |

A spec está tecnicamente completa e **aguarda apenas o aval formal do autor**
(ver o cabeçalho). Nada foi implementado e nada foi commitado.

---

## 7. Riscos

- **Base parada com público real** — o pior modo de falha do produto (resposta
  errada com cara de certa). Mitigado pelo passo 2 e pelo bloco de procedência do
  passo 3, que expõe a idade do dado em vez de escondê-la.
- **Ruído fica visível.** A interface expõe o que uma resposta de agente
  disfarçava. Achados concretos do protótipo, todos na base hoje: "Mezona Lab"
  (oficina de Ableton das 19h às 22h) listado como festa; "REM 3 — Rota dos Reis"
  (retiro matrimonial, R$ 3.458) no catálogo de vida noturna; eventos da agenda do
  Ordinário caindo às 00h quando o flyer não traz horário, o que os joga para o
  dia seguinte na lista ordenada. Nenhum é bloqueador, mas os três ficam expostos
  no segundo em que a interface existe. Alimenta o NI-04 (ruído v2).
- **Custo recorrente do Monid** vira diário (§3 passo 2).
- **Limites do free tier** (Neon hiberna, cold start no serverless) — aceitável
  para um punhado de usuários; medir antes de prometer disponibilidade.
- **Roteamento do `vercel.json`** — risco de derrubar o MCP ao adicionar o site.
- **Plano Vercel Hobby não cobre uso comercial.** Ciente e aceito pelo autor em
  2026-07-26: enquanto o projeto for gratuito e sem receita, está dentro dos
  termos. **Gatilho para reavaliar:** qualquer receita, patrocínio ou uso
  comercial exige migrar para o plano Pro. Registrar no PRD §7 (custo) quando
  esta spec for aprovada — é decisão de projeto, não questão em aberto.

---

## 8. O que muda fora do código quando esta spec for aprovada

- **`docs/PRD_MVP.md` §4 e §9:** nota registrando que a cláusula condicional
  ("cara própria só entra se provar vantagem") foi fechada pela demanda
  espontânea de 2026-07-26, e que o site entra como segunda porta — sem promover
  o site a produto principal.
- **`docs/PRD_MVP.md` §7 (decisões travadas — custo):** registrar o gatilho do
  plano Vercel Hobby (§7 desta spec) e o Monid como custo recorrente diário.
- **`docs/PRD_MVP.md` §8 (riscos — "Legal / Termos de Uso"):** hoje diz só "a
  avaliar"; passa a registrar a postura decidida (agregador com atribuição) e o
  anexo `tos.md` como referência.
- **`docs/PRD_MVP.md` §6 (Fases 1 e 2 — instrumentação):** registrar PostHog como
  a plataforma, cobrindo as duas portas.
- **`docs/backlogs/nao-iniciado.yaml`:** NI-10, NI-11 e NI-21 passam a
  `status: em-andamento`; entra **NI-28** (site público de leitura) — próximo
  código livre, já que o maior em uso é NI-27.
- **`CLAUDE.md`:** ganha o site nos comandos e na arquitetura (incluindo o
  runtime Node novo, que hoje não existe no repo), e o README passa a ser o
  documento de entrada para humanos.

### 8.1 Defasagem do PRD que NÃO foi causada por esta spec

Levantado em 2026-07-26 ao checar os pontos que a spec toca. O `PRD_MVP.md` está
marcado como "Última atualização: 2026-07-10" e acumulou 16 dias de entregas que
não foram refletidas. Não é escopo desta spec corrigir, mas fica registrado para
não se perder — o PRD é a fonte da verdade e hoje afirma coisas que deixaram de
ser verdade:

- **§6 apresenta a Fase 0b como "(próximo passo)"** (linha 230). Ela **fechou em
  2026-07-11**: NI-09 + NI-20 implementados e o critério validado pelo autor
  (consulta pelo celular com o PC desligado).
- **§7 diz "Custo: só free tier + soluções locais. Nada de cloud paga"**
  (linha 316). Isso foi **conscientemente excepcionado em 2026-07-23** com o
  Monid (~$0,006/perfil/rodada), aprovado pelo autor e registrado no backlog —
  mas não no PRD, que segue contradizendo a realidade do projeto.
- **§6, trilha de dados:** o item 2 (cinema) foi entregue em 2026-07-11 e o item
  3 (Instagram) em 2026-07-23; ambos ainda são descritos como futuros.
- **Cabeçalho:** a data de última atualização precisa acompanhar.

Nada disso foi feito ainda — a spec está em rascunho e não houve commit.

## 9. Fora de escopo

- **Imagens/capas de evento no site.** Adiado pelo autor em 2026-07-26 (§3 passo
  3), não descartado. O que já foi levantado, para não se perder quando o tema
  voltar: (a) a base já guarda `imagem`, exceto para `fonte='instagram'`, que é
  NULA por desenho — o caso exige fallback, não é uniforme; (b) a URL do CDN pode
  morrer sem aviso (evento despublicado, CDN rotacionado), então o front precisa
  tratar erro de carregamento; (c) `next/image` não otimiza host externo sem
  liberar os domínios em `images.remotePatterns` (Sympla, Cloudinary do Shotgun,
  S3 do Ticket and Go, Ingresse) — fonte nova quebra a imagem em silêncio; (d)
  hotlink reabre a dimensão de servir o *asset* da plataforma de origem, que hoje
  o v1 evita (anexo `tos.md`).
- Compra de ingressos, contas de usuário no site, pagamentos.
- Outras cidades (o schema já é cidade-aware; acender cidade nova é decisão
  posterior).
- Chat em linguagem natural no site (descartado em 2026-07-26 por custo de LLM
  por pergunta; o caminho para linguagem natural continua sendo o MCP).
- Enriquecimento v2 / classificação de gênero por LLM (NI-05) — independente
  desta spec, ainda que a interface torne a falta de gênero mais visível.
- Escalar a extração do flyer para CI (§3 passo 2, alternativa descartada).
