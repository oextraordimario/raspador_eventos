# Spec — Instagram como fonte de contexto E de eventos (NI-06 + NI-24 + NI-26 + NI-25)

> **Status: APROVADA em 2026-07-23** (decisões da §3 confirmadas pelo autor na
> revisão; implementação delegada ao Claude com revisão do autor só no final —
> por isso a §5 é um plano de validação AUTOEXECUTÁVEL, não um roteiro manual).
>
> **O quê/por quê:** muita casa de Brasília divulga a agenda SÓ no Instagram —
> ingresso na porta, sem página de venda. Casos reais do autor: o **Culto** tem
> evento de terça a sábado e quase nada vai pro Sympla; o **Ordinário** faz pagode
> a R$ 20 divulgado só no Insta. Sem essa fonte, o raspador enxerga um recorte
> falso da vida noturna — o PRD (§3/§6) já tratava o Instagram como etapa
> **necessária** do MVP. O spike `spikes/instagram-monid/` (2026-07-21) desriscou
> a parte historicamente proibitiva (login wall/bloqueio/layout): a raspagem sai
> por API paga (Monid → TikHub), em JSON, sem navegador.
>
> **Mudança de ambição vs. o NI-06 original:** o Instagram deixa de ser SÓ
> contexto de eventos existentes — ele também é **origem de eventos** que não
> existem em nenhuma plataforma de ingresso (o caso Culto/Ordinário). Os dois
> papéis estão nesta spec.
>
> **Contexto de infra:** tabelas novas via `CREATE TABLE IF NOT EXISTS` — **não
> precisa descartar a base**. Eventos derivados do Instagram entram na tabela
> `eventos` existente (fonte nova `instagram`), reaproveitando dedupe, FTS,
> consulta e MCP sem mudança.

---

## 1. O que o spike já garantiu (não rediscutir)

Ver `spikes/instagram-monid/README.md`. Resumo do que esta spec assume:

- `fetch_user_posts` ($0,003/call) → posts com legenda completa, hashtags,
  menções, `taken_at`, imagem 1080px; `fetch_user_stories` ($0,003) → stories
  ativos com mídia e stickers (`story_link_stickers`, `story_countdowns`).
- **O flyer (imagem) carrega dado que a legenda não tem** (caso Alquimia Dark:
  data, preço e line-up só na imagem) → leitura por visão é obrigatória, não
  opcional.
- URLs de mídia **expiram** (~horas): baixar na hora da ingestão.
- `location` do payload costuma vir nulo: o "onde" é o próprio perfil (a casa) —
  por isso a watchlist carrega o vínculo perfil → casa.
- Chave do Monid mora no config do CLI (`monid keys add`), **nunca no repo**;
  chamar via `subprocess` (padrão do probe) evita as pegadinhas de shell no
  Windows.

## 2. Design

### 2.1 Watchlist de perfis (NI-24) — `dados/perfis_instagram.yaml`

Arquivo YAML **versionado no repo** (pasta nova `dados/`), uma entrada por `@`:

```yaml
- usuario: cultorockbar          # o @ (sem arroba)
  nome: Culto Rock Bar           # nome canônico da casa → vira local_nome do evento
  tipo: casa                     # casa | produtora
  ativo: true                    # false = pula na rodada, sem apagar histórico
  local_aliases: ["Culto", "Culto Rock Bar"]   # grafias vistas nas plataformas de ingresso (ajuda a conciliação §2.7)
```

**Por que arquivo e não tabela:** a base é **descartável** por convenção
(`DROP SCHEMA` a cada mudança de schema) — dado **curado à mão** não pode morar
só nela. YAML versionado sobrevive ao drop, é diff-able no git e o atrito de
adicionar casa nova é editar 5 linhas (ou pedir pro Claude). Quando o NI-16
(casas como entidade) sair, o YAML vira a semente da tabela `locais` — não o
contrário.

Recorte inicial: o Mário monta a lista (dezenas de casas; começar pequeno:
Culto, Ordinário + as recorrentes do dogfooding). Raspar é barato
(~$0,006/perfil/rodada), então a lista pode crescer sem dó.

### 2.2 Scraper (NI-06) — `src/scrapers/instagram.py`

**Contrato próprio**, como o cinema: devolve payloads brutos por perfil, não
lista de eventos (o evento nasce na derivação, §2.6).

- `raspar(perfis)` → para cada `@` ativo: 1 call `fetch_user_posts` + 1 call
  `fetch_user_stories`, via `subprocess` no CLI `monid` (fire-and-poll do probe,
  promovido a código de produção com timeout e erro por perfil).
- Tolerância a falha **por perfil** (invariante do NI-06): perfil que falhar é
  logado em `execucoes.erros` e não derruba a rodada.
- `ULTIMA_RASPAGEM`: `coletados` = perfis que responderam, `total_site` = perfis
  ativos na watchlist (o medidor de cobertura mede o recorte, padrão NI-22).
- **Mídia**: baixa a imagem 1080px de cada post **novo** (shortcode ainda sem
  payload na Bronze) para `midias/instagram/<code>.jpg` (pasta local,
  gitignorada). A imagem serve à extração (§2.3) e fica como auditoria; não vai
  pro Postgres (peso no free tier do Neon sem consulta que justifique).

### 2.3 Leitura do flyer (NI-26) — extração por subagente multimodal

Passo **incremental** (como o "descrever"): roda 1 vez por post novo, nunca
re-extrai shortcode já processado.

- **Executor:** `claude -p` headless (Sonnet), decisão já travada no PRD §7 —
  assinatura, não API paga. O prompt manda ler `midias/instagram/<code>.jpg` +
  a legenda, e devolver JSON estruturado:

```json
{"e_evento": true, "confianca": "alta",
 "nome": "Alquimia Dark", "data": "25/07", "hora": "21:00",
 "preco": 20.0, "lineup": ["GABZ", "VELOZZ"], "local": null,
 "observacoes": "entrada 20$ na porta"}
```

- Legenda e flyer entram **juntos** na mesma chamada (1 call por post): a
  legenda valida o flyer e vice-versa (mitiga "flyer estiliza/mente" do NI-26).
- O JSON extraído é gravado na Bronze (`instagram_raw`, origem `extracao`) —
  a derivação (§2.6) trabalha a seco a partir dele, no padrão da casa: regra
  nova de derivação **não** exige re-extrair.
- **Ano da data:** flyer traz "25/7" sem ano → inferir a **próxima ocorrência
  ≥ `taken_at`** do post (post de julho falando de 25/7 = este ano; post de
  dezembro falando de 5/1 = ano que vem). Ano explícito no passado =
  retrospectiva, não vira evento.
- Detalhes fixados na implementação (2026-07-23): (a) post com mais de
  **60 dias** (`EXTRAIR_POSTS_DIAS`) não vale extração — protege a 1ª rodada
  de um perfil novo de gastar visão com feed histórico; (b) o subprocesso do
  `claude -p` roda **sem `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`** no env
  (chave de API tem precedência sobre o login da assinatura no CLI e furaria
  a decisão do PRD §7 — visto na prática na validação da camada 2).

### 2.4 Stories — guardar sim, visão ainda não

Meio-termo (dúvida do autor registrada): a call de stories é barata e o payload
traz de graça **stickers estruturados** — link de ingresso
(`story_link_stickers`), contagem regressiva (`story_countdowns`), hashtags.

- **v1 raspa e guarda** os stories na Bronze (metadados + stickers; a mídia do
  story NÃO é baixada nem processada por visão).
- Uso imediato: link de ingresso em sticker é sinal forte pra conciliação
  (§2.7) e o countdown carrega data de evento de graça.
- **Visão de vídeo/frame de story fica FORA do v1** — reabrir se o dogfooding
  mostrar evento que só existiu em story (aí decide-se extrair frames).
- Ressalva honesta: story expira em 24h — rodada manual esparsa perde a maioria.
  O valor pleno dos stories só chega com o cron diário (NI-10). Aceito no v1.

### 2.5 Modelagem na base — Bronze nova, `eventos` intacta

```sql
-- Bronze do Instagram: payloads crus por post/story + extração do flyer.
CREATE TABLE IF NOT EXISTS instagram_raw (
    perfil     TEXT NOT NULL,   -- @ da watchlist
    code       TEXT NOT NULL,   -- shortcode do post (ou id do story)
    origem     TEXT NOT NULL,   -- 'post' | 'story' | 'extracao'
    payload    TEXT NOT NULL,   -- JSON bruto (post/story) ou JSON extraído (extracao)
    raspado_em TEXT NOT NULL,   -- ISO UTC "+00:00"
    PRIMARY KEY (code, origem)
);
```

Sem tabela "Prata de postagens" no v1: a Prata do Instagram **é a própria
`eventos`** (§2.6). Post que não vira evento fica só na Bronze (auditável,
re-derivável). Se o NI-16/NI-25 pedirem histórico de posts consultável, tabela
própria entra numa v2 — YAGNI agora.

### 2.6 Derivação — post vira linha de `eventos` (fonte `instagram`)

`derivar.aplicar_instagram(con)`, a seco, a partir de `post` + `extracao`:

- **Guarda de entrada:** só vira evento o post com `e_evento=true`,
  `confianca` alta, **data futura** resolvida (§2.3). Retrospectiva, meme e
  divulgação vaga ficam na Bronze sem virar evento — errar para o lado de
  NÃO criar (falso evento é pior que evento perdido: a plataforma de ingresso
  continua cobrindo o grosso).
- Mapeamento: `id = instagram:<code>` · `nome` extraído · `start_date` =
  data extraída + hora extraída (sem hora → `00:00`, precedente Ticket and Go)
  composta com `-03:00` · `local_nome`/`cidade`/`estado` **rotulados pela
  watchlist** (precedente Shotgun/TNG) · `url` = link do post ·
  `descricao` = legenda + campos do flyer formatados (vira FTS de graça) ·
  `atracoes` = lineup extraído · `organizador` = nome canônico do perfil.
- **Preço:** vira um lote sintético na tabela `lotes` (nome
  `"entrada (do flyer)"`, `preco` = valor extraído) — as agregações existentes
  (`preco_min`, `tem_gratis`) funcionam sem caso especial, e `detalhar_evento`
  mostra a origem do número no nome do lote.
- **`sumido` NÃO se aplica à fonte `instagram`:** o feed do perfil não é um
  catálogo de eventos futuros — post antigo sai da primeira página sem
  significar cancelamento. `_marcar_sumidos` pula a fonte (evento Instagram
  morre por data passada, como qualquer outro).

### 2.7 Conciliação (NI-25) — reusar o dedupe cross-fonte

Insight central: como o post virou linha de `eventos`, **o problema do NI-25 já
é o problema que o dedupe v1 resolve** (mesmo dia + nome/local similares,
cross-fonte). Nada de mecanismo novo:

- **MATCH** (post ↔ evento do Sympla/Zig/etc.): o dedupe agrupa; o canônico
  segue sendo a plataforma de ingresso (`_PREF_FONTE` ganha
  `instagram: 5`, último da fila — quem vende ingresso tem o dado transacional).
  O agente vê o link do post em `outras_urls` do canônico.
- **GAP** (festa só no Insta — o caso Culto/Ordinário): não agrupa com ninguém
  → o evento `instagram` fica canônico sozinho e **aparece na busca** como
  qualquer evento. Missão cumprida sem código novo.
- Ajuda ao matcher: `local_aliases` da watchlist entram na comparação de local
  (o Sympla escreve "Culto Rock Bar", o perfil é "@cultorockbar").
- Risco conhecido: nome extraído do flyer difere do nome na plataforma
  ("Pagode do Ordinário" × "ORDINÁRIO APRESENTA: PAGODE") → calibrar limiar nos
  casos reais; falso NÃO-match é tolerável no v1 (o evento aparece duplicado,
  não some — e alimenta a calibração do NI-01).

### 2.8 Pipeline (`atualizar.py`)

Passo novo `instagram`, depois do cinema e antes do derivar:

```
raspar 5 fontes → sumidos → descrever → precificar → cinema
  → INSTAGRAM: raspar posts/stories (watchlist) → baixar mídia nova → extrair (claude -p, só posts novos)
  → derivar (inclui aplicar_instagram) → enriquecer → FTS → relatório → execucoes
```

- Flag `--sem-instagram` (simetria com `--sem-shotgun`/`--sem-cinema`; útil
  offline do Monid ou sem o CLI `claude` no PATH).
- `--so-derivar` re-deriva eventos do Instagram de graça (extração já está na
  Bronze) — regra nova de derivação sem gastar call nem token.
- Relatório/`execucoes`: fonte `instagram` aparece sozinha (dicts por fonte);
  o detector de queda >50% passa a vigiar o Monid de graça.

### 2.9 Consulta / MCP — zero mudança

`consulta.py` e `mcp_server.py` são agnósticos de fonte. Evento do Instagram
entra na busca, no filtro de data, no FTS (legenda + extração indexadas) e no
`detalhar_evento` (descrição inteira + lote sintético) sem tocar em nada.

## 3. Decisões (confirmadas pelo autor em 2026-07-23)

1. **Watchlist em YAML versionado** (§2.1), não tabela — base é descartável;
   dado curado não pode morar só nela. O Mário mantém a lista.
2. **Evento só-Instagram ENTRA em `eventos`** (§2.6) — é O caso de uso
   Culto/Ordinário.
3. **Stories sem visão no v1** (§2.4) — guardar payload + stickers, não
   processar vídeo.
4. **Custo recorrente aceito** (§7) — primeira exceção consciente ao
   "free tier only" do PRD (~$0,20/rodada de Monid; insumo de dado).
5. **Cadência segue manual** até o Insta estar lapidado — NI-10 (cron) não é
   antecipado. Restrição consciente: rodada esparsa perde stories (§2.4) e o
   acoplamento ao `claude -p` da assinatura (§2.3) terá que ser repensado
   quando o cron chegar.
6. **1 página de posts por perfil** (~12 posts/call) — a Bronze acumula rodada
   a rodada; não há necessidade de histórico. Paginar só se o dogfooding
   mostrar buraco.

## 4. Fora de escopo (v1)

- **Visão de vídeo/stories** (frame extraction) — §2.4; reabrir com caso real.
- **Comentários** (`fetch_post_comments`): sem uso mapeado que pague a call.
- **Descoberta automática de @s** (casa recorrente → achar o perfil): a
  watchlist é manual; automatizar é conversa do NI-16.
- **Tabela de casas/organizadores** (NI-16): o YAML é a semente, não a entidade.
- **Classificação de gênero/vibe (NI-05):** esta spec entrega o INSUMO (texto
  rico na descrição + FTS). O classificador é a spec seguinte — não misturar.
- **`upcoming_event` nativo do Instagram**: veio `null` no spike; conferir em
  outras casas custa 1 call de detalhe — fica pra depois.

## 5. Plano de validação (autoexecutável — implementação delegada, revisão só no final)

Acordo de trabalho (2026-07-23): o Claude implementa, testa e se auto-revisa;
o autor revisa o resultado no final. Logo a validação não pode depender de
conferência manual no meio do caminho — cada camada tem um cheque que o
próprio Claude roda e cujo resultado entra no relatório final de entrega.

**Camada 1 — testes de fumaça** (`tests/test_instagram.py`, banco descartável
`eventos_teste`, padrão `base_teste.py`; fixtures no formato dos payloads do
spike, sem rede pro Monid nem pro `claude -p` — o que se testa aqui é a
derivação/integração, não os fornecedores):

- Derivação: post + extração → evento `instagram:<code>` com data composta
  (`25/07` + taken_at de julho/2026 → `2026-07-25`), inferência de ano na
  virada (post de dezembro, evento em janeiro), lote sintético com o preço,
  hora ausente → `00:00`, hora presente → composta com `-03:00` e normalizada
  UTC na escrita.
- Guardas: `e_evento=false`, confiança baixa e data passada NÃO viram evento;
  re-derivar (`--so-derivar`) é idempotente (mesmo nº de eventos).
- Conciliação: fixture de evento Sympla "Culto Rock Bar" mesmo dia → dedupe
  agrupa, canônico = Sympla, post em `outras_urls`; evento só-Insta fica
  canônico e aparece em `buscar_eventos`; ruído/cancelado seguem escondendo.
- `sumido`: rodada posterior sem o post na página NÃO marca o evento Instagram
  (fonte fora do `_marcar_sumidos`).
- Regressão: `tests/test_enriquecer.py`, `test_bronze.py`,
  `test_observabilidade.py` e `test_zig_ticketandgo.py` continuam verdes
  (mexer em derivar/enriquecer/atualizar não pode quebrar o existente).

**Camada 2 — fumaça real de fornecedor** (gasta ~$0,01, aprovado): raspar 1
perfil real da watchlist (`@cultorockbar`) via scraper de produção, baixar a
mídia de 1 post novo e extrair com `claude -p` de verdade; conferir que o JSON
extraído passa na guarda e que o evento aparece em `buscar_eventos` no banco de
teste. É o único cheque que valida o contrato com Monid + CLI de visão de ponta
a ponta.

**Camada 3 — rodada real completa**: `python src/atualizar.py --sem-shotgun`
na base de produção, com a watchlist inicial; conferir no relatório a fonte
`instagram` com coleta > 0, erros por evento vazios no passo novo e os eventos
do Culto respondendo a uma consulta canônica ("o que tem no Culto essa
semana?") via `consulta.buscar_eventos`.

**Relatório de entrega** (o que o autor revisa): diff completo, saída das 3
camadas, custo real observado no painel do Monid e lista do que ficou fora
(fiel à §4).

## 6. Riscos

| Risco | Mitigação |
|---|---|
| Monid/TikHub fora do ar ou caro demais | Fonte de contexto com tolerância a falha por perfil; detector de queda >50% no relatório; eventos de plataforma seguem existindo |
| Flyer mente/estiliza → evento falso na base | Guarda de confiança + data futura (§2.6); legenda valida flyer na mesma chamada; errar pro lado de não criar |
| Ano inferido errado (flyer de evento anual) | Regra "próxima ocorrência ≥ taken_at"; teste de virada de ano trava a semântica |
| Post promocional sem data vira ruído | Não passa na guarda (sem data resolvida → não é evento) |
| Dedupe não casa Insta ↔ Sympla (nomes muito diferentes) | Tolerável no v1 (duplica, não some); `local_aliases` + calibração com casos reais |
| Custo por call escala com a watchlist | ~$0,006/perfil/rodada + extração só de post NOVO; teto natural = dezenas de casas ≈ $0,20/rodada |
| URL de mídia expirada na hora da extração | Baixar imediatamente após a call de posts, no mesmo passo |
| `claude -p` indisponível/limite da assinatura | Passo pula posts não extraídos e tenta na próxima rodada (fila natural: shortcode sem `extracao` na Bronze) |
| Legenda maliciosa manipula a extração (prompt injection) | Dano contido pela guarda (só nasce evento com nome+data+confiança alta) e pelo escopo do subagente (`--allowedTools Read`, sem rede/escrita); watchlist é curada — perfil hostil não entra sozinho |

## 7. Custo estimado (ordem de grandeza)

30 perfis × 2 calls × $0,003 = **~$0,18/rodada** de Monid; extração via
assinatura (custo zero marginal em dinheiro). Rodada diária ≈ **$5,50/mês**.
Dentro do "free tier + soluções locais" do PRD? **Não** — é o primeiro custo
recorrente em dinheiro do projeto. **Exceção aprovada pelo autor em 2026-07-23**
(o Monid é insumo de dado, ~1 café/mês; enquanto a cadência for manual, o
gasto real fica bem abaixo do teto diário).

## 8. v1.1 — Carrossel e agenda semanal (aprovada em 2026-07-23)

**Motivação (dogfooding do autor no dia da entrega do v1):** o post
`DbBhV7VFcZP` do @ordinariobar é um carrossel de 13 páginas com a AGENDA DA
SEMANA (7 eventos, um por dia) — e o v1 o descartou de propósito
(`e_evento=false`, regra "agenda não é evento" do prompt §2.3). Diagnóstico
confirmado na Bronze: a visão entendeu perfeitamente o post ("Post é a agenda
semanal do Ordi, não um evento único") e obedeceu a regra. O problema é a
regra: **quase toda casa divulga assim** — carrossel-agenda é o formato
principal, não a exceção. Taxonomia levantada pelo autor:

| Padrão | Realidade |
|---|---|
| Imagem única | info completa em imagem + legenda (v1 já cobre) |
| Carrossel, 1 evento | info pulverizada em VÁRIAS páginas |
| Carrossel-agenda | N eventos, um por página; legenda resume |
| Vídeo | capa + info no meio do vídeo — **fora de escopo** (custo/retorno ruim) |

Complicação transversal: casas postam a agenda na terça E o post individual
de cada evento no dia — o mesmo evento chega 2x e precisa conciliar.

### 8.1 Contrato de extração vira LISTA

O JSON extraído passa de objeto com `e_evento` para:

```json
{"eventos": [ {"nome": ..., "data": ..., "hora": ..., "preco": ...,
               "lineup": ..., "local": ..., "observacoes": ...,
               "confianca": "alta"} , ... ]}
```

0 itens = não-evento; 1 item = post comum; N itens = agenda. **Elimina a
ramificação**: não há "detectar agenda" — o caso único é a lista degenerada.
A regra "agenda → e_evento=false" morre. Guarda da derivação passa a valer
POR ITEM (nome + data resolvida + confiança alta).

### 8.2 Todas as páginas do carrossel

`baixar_midias(post)` baixa TODAS as páginas (`carousel_media[]`, teto de 15;
`midias/instagram/<code>_p<N>.jpg`) e todas entram na MESMA chamada de visão
(1 call por post; só sobe o nº de imagens no contexto). Cobre tanto a agenda
quanto o evento único com info espalhada. Vídeo continua como no v1 (frame de
capa via `image_versions`).

### 8.3 Identidade dos sub-eventos

- 1 item extraído → `instagram:<code>` e URL do post, como no v1 (compatível
  com o que já está na base).
- N itens → `instagram:<code>:<n>` (posição na lista extraída — estável
  porque a extração roda 1x e fica cacheada na Bronze) e URL
  `instagram.com/p/<code>/?img_index=<n+1>` (parâmetro real do Instagram:
  abre o carrossel na página aproximada; e dá a URL ÚNICA que o
  `detalhar_evento` exige).
- Datas passadas da agenda (postada na terça listando desde segunda): a regra
  do v1 já descarta de graça (data sem ano no passado rola o ano e estoura o
  teto `INFERENCIA_MAX_DIAS` → None).

### 8.4 Duplicação agenda ↔ post individual = dedupe INTRA-fonte (NI-01)

Rota escolhida (vs. merge na derivação, descartado por reimplementar dedupe e
fundir dado cedo demais): **implementar o NI-01** que já estava desenhado no
backlog. `_e_duplicata` deixa de exigir `fonte_a != fonte_b`; par da MESMA
fonte agrupa com regra mais apertada — mesmo dia + **mesmo local (obrigatório)**
+ similaridade de nome ≥ `SIM_NOME_INTRA` (0.55, a calibrar nos casos reais do
NI-01: "DEU BENZA" 3x na Arena CCB etc.). O canônico sai pela completude;
`preco_min` entra em `_CAMPOS_COMPLETUDE` para o post individual (que tem
preço do flyer) ganhar da linha da agenda. Efeitos aceitos: evento semanal
recorrente vira um evento POR SEMANA (dado real, âncora de mesmo-dia impede
agrupar semanas distintas); par que o dedupe perder aparece 2x (tolerável,
calibrável com `--so-enriquecer`).

### 8.5 Backfill sem re-raspar

A derivação ganha um adaptador do formato antigo de extração (objeto único →
lista de 0/1 itens), então nada re-extrai em massa. Re-extração dirigida: só
posts cuja extração está no formato antigo COM `e_evento=false` (candidatos a
agenda perdida) voltam pra fila — 1 vez, na rodada seguinte. Extração nova com
`eventos: []` NÃO re-tenta (não-evento é resposta válida).

### 8.6 Validação (mesmas 3 camadas do §5)

Camada 1: fixtures novas — carrossel-agenda (3 itens → 3 eventos com
`?img_index`), item com data passada descartado, adaptador do formato antigo
(true deriva, false não), dedupe intra-fonte (casos reais do NI-01 agrupam;
duas festas distintas da mesma casa no mesmo dia NÃO agrupam; agenda ↔ post
individual agrupa com canônico no individual). Camada 2: re-extração real do
`DbBhV7VFcZP` (13 páginas) e conferência dos 7 eventos. Camada 3: rodada
`--so-derivar` + rodada real; consulta canônica "o que tem no Ordinário essa
semana" respondendo os dias da agenda.
