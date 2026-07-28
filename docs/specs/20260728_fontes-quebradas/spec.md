# Spec — Fontes quebradas: Ticket and Go (API desligada) e Shotgun (zero no CI) — NI-57/58/59

> **Status: IMPLEMENTADA em 2026-07-28** — com um desvio importante: a
> estratégia escolhida na §2.1 **reprovou no teste de recall da §5.1** (1%) e
> foi substituída. O plano original fica preservado abaixo; o que foi feito de
> verdade, e por quê, está na **§7**. Ler as duas: a §2.1 registra o raciocínio
> que a medição derrubou.
>
> **O quê/por quê:** duas das cinco fontes de vida noturna pararam de coletar, e
> o raspador não parou junto — continuou gravando rodada "com sucesso" enquanto
> a base envelhecia. Em 28/07 o Ticket and Go passou a falhar com 404 (a API
> interna que usávamos foi **desligada**) e o Shotgun devolve **0 eventos desde
> a primeira rodada no GitHub Actions** (26/07), sem erro. Juntas, as duas
> fontes respondem por ~116 dos eventos futuros da base — o maior buraco de
> cobertura desde o início do projeto.
>
> **Terceiro item, transversal:** a coleta zerada do Shotgun não ficou só em
> "não atualizou". Como a fonte não levantou exceção, o `_marcar_sumidos`
> tratou o silêncio como catálogo vazio e marcou `sumido=1` em TODOS os eventos
> futuros do Shotgun — a consulta os escondeu. Um scraper quebrado apagou dado
> bom da vista dos usuários. Isso é um defeito de projeto do pipeline, não do
> scraper, e é o que a §3.3 corrige.

---

## 1. Diagnóstico — o que já está verificado (não rediscutir)

Tudo abaixo foi reproduzido em 2026-07-28 contra as APIs/sites reais. Não são
hipóteses; a implementação parte daqui.

### 1.1 Ticket and Go — a API V1 foi desligada, o front migrou para a V2

| Chamada | Antes | Hoje |
|---|---|---|
| `POST {V1}/eventos/pesquisa` (catálogo) | catálogo inteiro | **404** |
| `GET {V1}/eventos/{slug}` (detalhe/tickets) | detalhe c/ bilhetes | **404** |
| `GET {V1}/` (raiz) | — | 200 `cdn-api_3.4.5 - branch workspace!` |

O host está de pé — as **rotas** morreram. O bundle do SPA
(`https://www.ticketandgo.com.br/assets/index-ba12ccb8.js`, Vue/Vite) mostra
para onde o front foi:

```js
const baseUrlApiTicketAndGo = "https://production-api-v1-service.ticketandgo.com.br",
      laravelUrl            = "https://production-api-v2-service.ticketandgo.com.br";

obterTodosEventos(filtro="", page=1, perPage=12) { "/api/v2/site/list/all" ... }   // V2
obterEventosHome()                               { "/api/v2/site/list/main" }      // V2
obterEvento(slug, params)                        { `/eventos/${slug}/evento` }     // V1, rota NOVA
```

Ou seja: **listagem migrou para a V2 (Laravel); o detalhe continua na V1, mas
com o sufixo `/evento`** — que é exatamente o que faltava no nosso scraper.

**Listagem V2** — `GET {V2}/api/v2/site/list/all?filter=&page=1&perPage=100`:

```json
{"lista_evento_geral": [
   {"uuid": "53ecf2fd-…", "slug": "trust-love-2807", "nome": "Trust Love - 28/07 …",
    "categoria": "festival ou show", "inicio": "2026-07-28", "fim": "2026-07-28",
    "local": "Caalex", "imagem": "https://s3…/event/69f5201ab5644.webp"}],
 "pagination": {"total": 3689, "per_page": 100, "current_page": 1}}
```

Payload **muito mais magro** que o catálogo V1. Sumiram da listagem: hora,
descrição, endereço, lat/lon, id numérico. E o catálogo nacional pulou de ~460
para **3689** eventos (37 páginas a 100/página).

**Detalhe V1 (rota nova)** — `GET {V1}/eventos/{slug}/evento` devolve o que a
listagem não tem:

```
id = 32684                 ← NUMÉRICO, preservado: a chave `ticketandgo:<id>` não muda
uuid, slug_evento, nome, nome_tipo_evento
inicio "2026-07-28", hora_incio "18:00:00", fim, hora_fim   ← o typo "incio" continua
descricao (HTML), imagem, banner, gratuito, classificacao_etaria
taxa_conveniencia 0.1      ← fração, como antes
setores[] → bilhetes[]     ← lotes (o derivar JÁ lê esse formato: derivar._lotes_ticketandgo)
sessoes[] {data_inicio, data_fim}
endereco = []              ← SEMPRE VAZIO (testado em 6 eventos)
cidade / estado / latitude / longitude → ausentes ou nulos
```

Duas consequências importantes:

1. **A chave dos eventos não muda** (`id` numérico veio junto no detalhe), então
   os 75 eventos do Ticket and Go que já estão na base são atualizados, não
   duplicados. O `_lotes_ticketandgo` do `derivar.py` já lê `setores[].bilhetes[]`
   e `taxa_conveniencia` — **a camada Prata não precisa mudar**.
2. **O endereço sumiu da API pública.** O filtro de DF do scraper
   (`_do_df`, textual sobre `local` + `endereco_completo`) perdeu seu principal
   insumo. Sobra só `local` (nome do lugar, ex.: "Caalex"), que não diz cidade.
   É o problema central desta parte da spec — tratado na §2.1/§3.1.

**Sobre o `filter=` da V2** (medido hoje):

| filtro | total |
|---|---|
| *(vazio)* | 3689 |
| `brasilia` / `Brasília` | **114** |
| `DF` | 3 |
| `taguatinga`, `asa sul` | 0 |

E o mais relevante: `filter=brasilia` devolve eventos cujo **nome e `local` não
contêm "brasilia"** — ex.: "DIA 17/07 - Constelações Contemporâneas" no *Teatro
Nacional Claudio Santoro*. Isso é evidência de que o filtro server-side alcança
um campo de endereço/cidade que a API **não expõe** no JSON. É a brecha que
torna o recorte DF ainda possível — e é também a maior incerteza da spec, por
isso a §5 mede o recall dele contra um gabarito real.

Parâmetros `uf=`, `estado=`, `cidade=`, `city=` são **ignorados** (total continua
3689). `perPage=1000` não foi confirmado — testar se o servidor respeita ou faz
clamp.

### 1.2 Shotgun — o scraper funciona; o **ambiente do CI** é que devolve zero

Rodado local hoje, com o mesmo código de `src/scrapers/shotgun.py`:

```
page 1  slugs 28  novos 28  acumulado 28
page 2  slugs 42  novos 14  acumulado 42
page 3  slugs 56  novos 14  acumulado 56
slug infinurecebeseupereiraembsb -> JSON-LD: True  "Infinu Recebe Seu Pereira…"  2026-07-28T23:00:00Z
```

No GitHub Actions, as três rodadas existentes deram `shotgun 0/0`:

| rodada | onde | coleta |
|---|---|---|
| 2026-07-17 10:56 | local | 77 |
| 2026-07-26 15:40 | Actions (dispatch) | **0** — com `*** ALERTA shotgun: coleta caiu 100% (77 → 0)` |
| 2026-07-27 09:39 | Actions (cron) | **0** |
| 2026-07-28 08:24 | Actions (cron) | **0** |

Ou seja: **quebrou exatamente quando saiu da máquina do autor e entrou no
runner.** O site já bloqueava HTTP puro com 429 (é o motivo de existir o
Playwright ali); a hipótese de trabalho é bloqueio anti-bot para IP de
datacenter (Azure) — challenge/página vazia servida ao runner. Faltam
evidências do lado de lá: hoje o scraper não guarda nada quando a listagem vem
vazia, então o CI não deixou rastro nenhum.

Dois não-problemas descartados no caminho, para não virarem caça-fantasma:

- `/pt/cities/brasilia` **redireciona** para `/en/cities/brasilia` e os links
  agora vêm como `/en/events/<slug>`. A regex `r'/events/([a-z0-9-]+)'` não é
  ancorada, então continua casando. Não é a causa.
- O JSON-LD dos eventos continua íntegro (`MusicEvent`, com `startDate`).

### 1.3 O dano colateral: coleta zerada vira "sumido"

`atualizar.py:143 _marcar_sumidos` pula fonte que **falhou** (`"erro" in res`) —
mas o Shotgun não falhou: devolveu `{"coletados": 0, "total_site": 0}` com
sucesso. Resultado: todo evento futuro do Shotgun tinha `raspado_em` anterior ao
início da rodada e foi marcado `sumido=1`, sumindo da consulta. O relatório de
27/07 mostra o efeito (45 sumidos, a maioria `[shotgun]`: "Festa Homem 5 Anos",
"Noize + Suave Baile", "Infinu Recebe Tuyo…").

O alerta de queda >50% funcionou (disparou em 26/07) — mas é só um `print`.
Ninguém leu, e o pipeline seguiu apagando dado bom por três dias. **Detector
sem freio não é proteção.**

---

## 2. Decisões (recomendação do Claude; a palavra final é do autor)

### 2.1 Como recortar o DF no Ticket and Go sem endereço?

| # | Opção | Custo/rodada | Recall | Veredito |
|---|---|---|---|---|
| A | Varrer o catálogo (37 páginas) + detalhe de todos os futuros | milhares de requests | 100% | inviável |
| B | **Buscar por dicionário de termos DF via `filter=`, detalhe só dos achados** | ~30 buscas + ~120 detalhes | a medir (§5.1) | **recomendada** |
| C | Varrer o catálogo e filtrar por `local` contra uma lista de casas DF conhecidas | 37 requests | baixo, frágil | não |
| D | Achar outra rota que devolva o endereço | ? | ? | investigar antes de B (30 min, timebox) |

**Recomendação: D como timebox curto, depois B.** A opção D é barata de testar
(procurar no bundle rotas de endereço/local e tentar `GET /eventos/{uuid}/…`);
se aparecer endereço, o `_do_df` original volta a funcionar sem mudança de
doutrina. Não aparecendo, vale a B, com o dicionário de termos = `brasilia`,
`df`, `distrito federal` + as RAs (taguatinga, ceilândia, gama, sobradinho,
planaltina, águas claras, guará, samambaia, santa maria, são sebastião,
paranoá, recanto das emas, riacho fundo, núcleo bandeirante, cruzeiro, lago
sul, lago norte, sudoeste, octogonal, jardim botânico, brazlândia, itapoã,
vicente pires, arniqueira, park way, candangolândia, varjão, estrutural,
asa sul, asa norte).

**Postura mantida:** o filtro erra para o lado de **perder** evento, nunca de
poluir a base com outra cidade (é a regra calibrada no spike original). Se um
termo trouxer evento claramente de fora (ex.: "Café de Negócios Barra da
Tijuca" casando "df" por acaso), a guarda é o `local`/nome — e na dúvida, fora.

### 2.2 O que fazer com o Shotgun no CI?

**Recomendação: instrumentar primeiro, decidir depois.** Não dá para escolher a
mitigação (stealth? proxy? sair do CI?) sem saber o que o runner recebe.
Sequência: (1) o scraper passa a falhar alto e a guardar evidência; (2) uma
rodada de CI com essa instrumentação; (3) com o HTML/screenshot na mão, a
mitigação vira uma escolha de um parágrafo, não uma sequência de tentativas às
cegas.

Se a evidência confirmar bloqueio por IP, a saída **provável** (a confirmar
depois, fora desta spec) é tirar o Shotgun do cron e rodá-lo local junto do
`--so-instagram`, que já é uma rodada local recorrente e obrigatória. Trocar o
runner por proxy residencial pago não se paga por ~50 eventos/semana.

### 2.3 Recuperar o que o `sumido` escondeu?

**Recomendação: sim, e é de graça** — `_marcar_sumidos` é idempotente: basta
uma rodada local do Shotgun (que hoje funciona) para os eventos reaparecerem
com `sumido=0`. O que **não** volta sozinho é o que o `DROP` de 27/07 apagou;
essa perda já está registrada no CLAUDE.md e não é escopo daqui.

---

## 3. Design

### 3.1 `src/scrapers/ticketandgo.py` — reescrita do contrato de rede

O módulo mantém a assinatura pública (`raspar()`, `raspar_tickets(slug)`,
`ULTIMA_RASPAGEM`) — nada muda em `atualizar.py`, `derivar.py` ou no schema.
Muda só como ele conversa com a fonte:

```
API_V1 = "https://production-api-v1-service.ticketandgo.com.br"
API_V2 = "https://production-api-v2-service.ticketandgo.com.br"

raspar():
  1. para cada termo do dicionário DF:
       GET {V2}/api/v2/site/list/all?filter=<termo>&page=N&perPage=100
       (paginar por pagination.total; parar quando esgotar)
  2. união dos itens por `uuid` (o mesmo evento aparece em vários termos)
  3. descartar quem já é passado por `fim`/`inicio` (data sem hora — margem de
     1 dia, ver §4)
  4. para cada candidato futuro:
       GET {V1}/eventos/{slug}/evento   → payload rico
       normalizar com o `id` NUMÉRICO do detalhe (chave estável)
  5. `_do_df` reaplicado sobre nome + local do detalhe como segunda barreira
  6. ULTIMA_RASPAGEM = {total_site: candidatos DF, coletados: normalizados}

raspar_tickets(slug):  GET {V1}/eventos/{slug}/evento    (mesma rota; o payload
                       já traz setores[].bilhetes[] + taxa_conveniencia)
```

Pontos de atenção da normalização:

- `start_date` = `_quando(inicio, hora_incio)` — **inalterado**, o typo da fonte
  continua. Só que agora hora vem do detalhe, não do catálogo.
- `endereco`, `lat`, `lon` passam a ser **sempre None**. Aceitável: `local_nome`
  continua preenchido e é o que o FTS e o front usam. Registrar no docstring
  para ninguém "consertar" isso depois achando que é bug.
- `descricao` continua vindo pronta (agora do detalhe) — a fonte **segue fora**
  do passo "descrever" do `atualizar.py`.
- `_raw` = payload do detalhe (não mais o item do catálogo). A Bronze fica com
  o payload rico, que é estritamente melhor. Origem continua `catalogo`.
- Uma requisição de detalhe por evento futuro DF (~120) com a mesma `pausa` de
  hoje. É mais tráfego que antes (era 1 chamada), mas é o que a fonte permite.

**O `derivar.py` não muda.** Confirmado: `_lotes_ticketandgo` já trata
`bilhetes[]` no topo *e* `setores[].bilhetes[]`, e a taxa continua fração.

### 3.2 `src/scrapers/shotgun.py` — falhar alto e deixar rastro

Duas mudanças pequenas, ambas sobre observabilidade — **nenhuma tentativa de
burlar bloqueio nesta spec**:

1. **Listagem vazia = exceção.** Se a página 1 não render nenhum slug, levantar
   `RuntimeError("listagem sem slugs — provável bloqueio/challenge")`. Hoje o
   módulo devolve lista vazia em silêncio, e é isso que envenena o
   `_marcar_sumidos`. Fonte que não coletou nada **não** é fonte que coletou
   zero.
2. **Evidência no disco.** Nesse caminho de falha, salvar `page.content()` e um
   `page.screenshot()` em `diagnostico/shotgun/` (gitignorado). No workflow,
   um passo `if: failure()` sobe a pasta como artifact
   (`actions/upload-artifact@v4`, retention curto). É o que permite decidir a
   §2.2 com dado em vez de palpite.

Fora de escopo aqui (só depois da evidência): stealth, proxy, mudança de
runner, ou tirar o Shotgun do cron.

### 3.3 `src/atualizar.py` — coleta zerada nunca marca sumido (NI-59)

A guarda que faltava, no `_marcar_sumidos`:

```python
for fonte, res in resultados.items():
    if "erro" in res or fonte in ("instagram", "cinema"):
        continue
    if not res.get("coletados"):        # coleta vazia ≠ catálogo vazio
        continue                         # ← NOVO
```

Racional para o comentário do código: catálogo de plataforma de ingresso não
esvazia de um dia para o outro; quando esvazia de verdade, os eventos morrem
por data passada — que já não é marcado. Então "coletados == 0" só acontece em
scraper quebrado, e o custo do falso negativo (um evento cancelado demora um
dia a mais para sumir) é ordens de grandeza menor que o do falso positivo
(agenda inteira de uma fonte escondida da consulta).

Complemento no relatório: quando uma fonte coleta 0 tendo coletado >0 na rodada
anterior, o alerta existente ganha a linha "sumidos NÃO recalculados para esta
fonte" — para o alerta explicar o que o sistema fez a respeito, não só gritar.

---

## 4. Casos de borda

- **Data sem hora na listagem V2.** O corte "é futuro?" na etapa 3 usa só
  `inicio`/`fim` (dia). Usar margem de 1 dia (`>= hoje - 1d`) para não perder
  evento que começa hoje à noite; a hora exata chega no detalhe e o
  `apenas_futuros` final decide com ela.
- **Slug ausente ou detalhe 404** (evento tirado do ar entre a listagem e o
  detalhe): pular o evento e contabilizar em `erros` da rodada, sem derrubar a
  fonte.
- **Mesmo evento em vários termos** do dicionário: dedupe por `uuid` antes do
  detalhe, senão o custo de rede triplica.
- **Termo DF que traz evento de outra cidade** (homônimo, "Brasília" no nome de
  evento em SP): a segunda barreira `_do_df` sobre nome+local decide; na dúvida,
  fora — a regra continua errando para o lado de perder.
- **`perPage` com clamp**: se o servidor ignorar `perPage=100`, a paginação por
  `pagination.per_page` real (não pelo pedido) evita loop infinito ou lacuna.
- **Bronze com payload de formato antigo**: `eventos_raw` guarda payloads V1
  antigos (origem `catalogo` e `tickets`). O `derivar` precisa continuar
  lendo os dois — hoje já lê, e como a derivação é reconstruída do zero a cada
  `--so-derivar`, um payload velho não pode virar exceção. Cobrir no teste.
- **Shotgun com listagem parcial** (página 1 ok, página 3 vazia): não é falha —
  o loop já para no primeiro `sem novos`. A exceção só dispara com **zero
  slugs na página 1**.

---

## 5. Plano de validação (autoexecutável)

### 5.1 Recall do recorte DF — o teste que decide a §2.1

Gabarito de graça: a base tem hoje **75 eventos futuros do Ticket and Go**
raspados quando a API antiga ainda respondia (com endereço, portanto com
recorte DF confiável). O critério:

```
python -c "…"   # 1) ler id/slug/nome dos ticketandgo futuros na base (gabarito)
                # 2) rodar a nova ticketandgo.raspar() sem gravar
                # 3) medir: quantos do gabarito reapareceram? quais faltaram?
```

- **≥ 95% de recall → estratégia B aprovada.**
- 80–95% → aprovada com o dicionário de termos ajustado pelos que faltaram.
- < 80% → a estratégia B não serve; voltar à §2.1 e decidir de novo (varredura
  completa com cache de detalhe, ou o Ticket and Go entra em modo degradado).

Medir também o inverso: eventos novos que a estratégia trouxe e o gabarito não
tem — amostrar 10 e conferir manualmente que são mesmo do DF (precisão).

### 5.2 Testes de fumaça

- `tests/test_zig_ticketandgo.py` (existente) — atualizar os fixtures do Ticket
  and Go para o payload V2/detalhe novo e manter os casos de: filtro DF, data
  composta com `-03:00`, lote com taxa fracionária. Continua rodando **offline**
  (fixture), como hoje.
- `tests/test_observabilidade.py` (existente) — caso novo: fonte com
  `{"coletados": 0}` não marca `sumido`; fonte com `{"coletados": N}` marca.
  Este é o teste do NI-59 e é o mais importante dos três.
- Rede real (manual, uma vez): `raspar()` + `raspar_tickets()` de um slug.

### 5.3 Ponta a ponta

```
python src/atualizar.py --sem-shotgun --sem-instagram --sem-cinema
python src/atualizar.py --so-derivar
```

Conferir no relatório: `ticketandgo` volta a coletar (~75+), `lotes` do Ticket
and Go voltam a existir, `preco_min` preenchido em ≥ 90% dos futuros dessa
fonte (era 93% em 28/07), e **nenhum** sumido novo por conta desta mudança.

### 5.4 Shotgun

- Local: `python src/atualizar.py` (com Shotgun) → coleta > 0 e os eventos
  antes marcados voltam com `sumido=0`.
- CI: disparar o workflow por `workflow_dispatch` e baixar o artifact de
  diagnóstico. **Entregável desta spec é a evidência**, não o Shotgun voltando
  a funcionar no CI.

---

## 6. Ordem de implementação

1. **NI-59** (guarda do sumido + linha no alerta) — 20 linhas, protege a base
   contra os dois problemas enquanto o resto é feito. Vai primeiro.
2. **NI-58** (Shotgun: exceção + evidência no CI) — pequeno, destrava a decisão
   da §2.2 na próxima rodada do cron.
3. **NI-57** (Ticket and Go): timebox da opção D → estratégia B → §5.1 → só
   então a reescrita e os testes.
4. Rodada local completa para restaurar os `sumido` do Shotgun.

**Riscos aceitos:** a API do Ticket and Go acabou de mudar sem aviso e nada
garante que a V2 seja estável — o custo de reescrever de novo é o preço da
fonte. Se ela quebrar uma terceira vez em poucas semanas, a decisão passa a ser
de produto (vale manter a fonte?), não técnica.

**Fora de escopo:** burlar bloqueio anti-bot do Shotgun; tornar `eventos`
reconstruível a partir da Bronze (NI-55); exportar as tabelas não-reconstruíveis
(NI-56). Os dois últimos ficaram mais urgentes depois deste episódio e seguem
no backlog.

---

## 7. O que a implementação mudou em relação ao plano (2026-07-28)

### 7.1 A opção D morreu; a B reprovou no teste

**D (achar outra rota com endereço):** o timebox achou a resposta, e é não.
`endereco` veio vazio em **18/18** eventos testados, o bundle não tem nenhuma
outra rota de endereço, e a **página pública renderizada também não mostra
endereço** — só o nome do local. A informação saiu da API, não está escondida.

**B (buscar por dicionário de termos DF no `filter=`):** medida contra o
gabarito de 79 eventos, deu **recall de 1% (1/79)**. A leitura da §1.1 estava
errada: o `filter` casa nome/produtora, não endereço — o "Constelações
Contemporâneas no Teatro Nacional" que parecia prova de filtro geográfico era
coincidência de outro campo. Todos os "Trust Love" no Caalex, em Brasília,
ficam invisíveis a `filter=brasilia`.

### 7.2 O que foi implementado: varredura completa + classificador de 3 sinais

O que destravou foi medir o tamanho real do problema, e não estimá-lo: o
catálogo nacional tem 3.640 eventos, mas **só 426 são futuros**. Varrer tudo
custa 37 requests e buscar o detalhe de todos os futuros custa ~430 — cerca de
**3 minutos**, na mesma ordem de grandeza do passo "precificar" que já existe.
A opção A tinha sido descartada por uma conta de guardanapo (3.689 detalhes)
que ninguém tinha checado.

Com o detalhe na mão de todos os futuros, o recorte DF virou classificação
textual em três sinais, do mais forte para o mais fraco (`_do_df`):

1. `local` na lista curada `dados/locais_df.yaml` (nome normalizado EXATO);
2. termo geográfico inequívoco no `local`/`nome`;
3. **CEP 70–73 ou `\bDF\b` na descrição** — sozinho cobre ~75% dos casos,
   porque a descrição costuma repetir o endereço completo.

Medição final contra o gabarito (§5.1): **77/77** dos eventos que continuam no
catálogo (os 2 restantes são eventos-teste que saíram do ar), **sem falso
positivo** — os únicos "extras" conferidos à mão eram DF de verdade e não
estavam no gabarito. Rodada real: 435 futuros → 81 DF → 80 normalizados.

Duas calibrações que vieram da medição, e valem como registro:

- **"Brasília" solto na descrição NÃO conta.** Pegava um evento em Uberlândia
  cujo endereço era "Jardim Brasília, Uberlândia - MG". Só CEP/UF contam no
  sinal 3.
- **Termo ambíguo fica fora**: Cruzeiro, Gama, Guará, Santa Maria, Varjão,
  Estrutural, Jardim Botânico, Sudoeste são RAs do DF *e* cidades/bairros de
  outros estados. Mantida a postura de errar para PERDER evento.
- A comparação do sinal 1 é por nome **exato normalizado**, não substring:
  "Comunidade das Nações - SIA" é do DF; "Comunidade das Nações São Paulo",
  não. Foi um falso positivo real durante a calibração.

`dados/locais_df.yaml` nasceu semeado com os 13 locais dos eventos que a base
já tinha da era com endereço — DF confirmado por dado, não por palpite. A cada
rodada o scraper imprime "candidatos a locais_df.yaml": locais que entraram só
por sinal textual, para curadoria manual (é o mesmo padrão da watchlist do
Instagram).

### 7.3 Efeitos colaterais que NÃO aconteceram

- A chave `ticketandgo:<id>` foi preservada (o id numérico veio no detalhe):
  os 79 eventos da base foram **atualizados**, não duplicados.
- `derivar.py` não mudou uma linha — `_lotes_ticketandgo` já lia
  `setores[].bilhetes[]`.
- `_precificar` não mudou: o slug continua saindo da URL pública e
  `raspar_tickets` aponta para a rota nova.

### 7.4 Dívida deixada

- `endereco`/`lat`/`lon` do Ticket and Go ficam **nulos** para sempre (a fonte
  não tem mais o dado). Documentado no docstring do módulo para ninguém
  "consertar" achando que é bug.
- O detalhe é buscado a cada rodada para os ~430 futuros nacionais, mesmo os
  que já se sabe não serem do DF. Cache negativo por slug resolveria, mas é
  otimização sem dor hoje (3 min).
