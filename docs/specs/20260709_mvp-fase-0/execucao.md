# Notas de execução e calibração — Fase 0 (núcleo)

Etapas 1–4 executadas em 2026-07-09, no mesmo dia da spec; **Etapa 5 (campos ricos)
executada na mesma data** — ver a seção própria no fim. Registro do que foi
**descoberto e calibrado** durante a implementação (o que não está no código nem
na spec).

## Cobertura — o que a investigação revelou

- **Sympla:** a paginação com `sort=month-trending-score` **esgota o catálogo**
  (256–257 ids em 3 páginas, conferido contra o `total` da API; página 1 sem sort
  não trouxe nenhum id fora do conjunto). Nada a mudar na coleta. A API **não tem**
  campo de tema/categoria mais rico: `event_type`/`type` é `'NORMAL'` em 100% do
  catálogo (verificado pedindo o objeto completo, sem `only`).
- **Ingresse:** `pagination.total = 4, total_pages = 1` — o catálogo de Brasília é
  realmente esse. Nada a mudar.
- **Shotgun:** a causa do horizonte de 3 dias era raspar **só a página 1** da
  cidade com scroll fixo. A listagem é paginada via `?page=N` (28 slugs na p.1,
  ~14 por página seguinte, 77 no total em 5 páginas, estáveis na p.6). O `raspar()`
  agora itera páginas até nenhuma trazer slug inédito. Resultado: 77/77 eventos,
  horizonte 2026-07-09 → **2027-04-10**.
  - Curiosidade operacional: a casa LAH **recicla slugs** de eventos semanais
    (ex.: slug `18-9-...` servindo o evento de 09/07). Inócuo: o JSON-LD lido na
    página traz sempre o evento atual, e o upsert por slug substitui.

## Ruído — calibração da lista

Rodada de auditoria sobre a base real (328 eventos) com heurística ampla para
caçar falsos negativos:

- **Adicionado `candidatura`**: 3 eventos de pré-candidatura política estavam na
  base ("Lançamento da Pré-Candidatura de Samuel Gaúcho" etc.). A palavra
  `lancamento` sozinha seria **perigosa** — marcaria "Lançamento do Álbum 'O
  Mago'" e "Lançamento Grupo Bendito", vida noturna real. `candidatura` pega só
  os políticos (há teste de regressão para os dois lados).
- **Deliberadamente NÃO marcados** (política: na dúvida, não marcar):
  - "Culto Confessions II" — pode ser festa (marca/balada), não culto religioso;
  - "Encontro de Clássicos do Fred Linhares" — encontro de carros antigos;
    `encontro` marcaria rodas de samba;
  - "feira" nunca pode virar termo: "SEXTA-FEIRA" contém a palavra.
- Estado final: **4 marcados** (1 anúncio de banda larga + 3 candidaturas),
  lista completa revisada, zero falso positivo.

## Dedupe — validação dos limiares

- Auditoria de todos os pares cross-fonte do mesmo dia com similaridade ≥ 0.45:
  **18 pares, todos eventos genuinamente distintos** (casas e nomes diferentes) —
  corretamente não agrupados. O par mais "apertado" foi "Pôr do Rock" (Cota Mil)
  × "Por Do Flow" (Lake Deck), sim 0.72 com casas diferentes: ficou abaixo do
  limiar forte (0.85), como deveria.
- A base recém-raspada **não tinha nenhuma duplicata cross-fonte real** no dia da
  execução (o par conhecido, "Sambinha da Copa" × "Samba da Passarinha" de 05/07,
  já era passado). O mecanismo está validado por teste sintético — incluindo o
  falso-positivo real "Varanda da Copa × Samba da Passarinha", que não pode
  agrupar — e ficará sob observação no dogfooding.
- Limiares mantidos como na spec: 0.85 (nome sozinho) / 0.55 + mesmo local.

## Critérios de aceite (spec §7)

Todos os 8 verificados em 2026-07-09:

1. ✅ `atualizar.py` ponta a ponta em base recém-apagada (150s, relatório completo).
2. ✅ Anúncio de banda larga com `ruido=1`, ausente de `buscar_eventos`.
3. ✅ Lista completa de marcados revisada (4 itens, só não-eventos).
4. ✅ Falso-positivo real não agrupado; colapso/`outras_urls` cobertos por teste
   (não havia duplicata real viva na base no dia).
5. ✅ Sympla 247/257 (os 10 faltantes são eventos passados — 100% dos futuros);
   Ingresse 4/4; Shotgun 77/77 com horizonte de 3 dias → 9 meses.
6. ✅ `tests/test_enriquecer.py` e `tests/test_mcp_server.py` passam.
7. ✅ `--so-enriquecer` re-marca sem raspar (0s).
8. ✅ `demo.py` delega para `consulta.buscar_eventos` (fim da comparação crua).

## Etapa 5 — campos ricos da fonte (executada em 2026-07-09)

### Sondagem: endpoints encontrados (HTTP puro, zero Playwright extra)

- **Sympla:** interceptando XHR na página do evento, achamos o BFF
  `event-page.svc.sympla.com.br/api/event-bff/purchase/event/{id}` — sem auth,
  responde a urllib. Traz `detail` (HTML) / `strippedDetail` e **`eventsCategory`**
  (a categoria real que a API de catálogo não dá). O `{id}` é o numérico no **fim da
  URL pública** (difere do id do catálogo). Há também `.../tickets/grouped` com
  preços — não usado (2ª requisição por evento; preço ficou só no Shotgun).
- **Ingresse:** `GET api-site.ingresse.com/events/{slug}` (estava no `/openapi.json`)
  traz `description` (HTML).
- **Shotgun:** JSON-LD da página (já visitada) traz `description`, `performer`,
  `organizer`, `offers` — capturados no próprio `_normalizar`.

Resultado na base recriada: descrição em **100% Shotgun (77), 100% Ingresse (4),
94% Sympla (243/257** — os 14 restantes não têm descrição na origem; 0 falhas).
Preço em 77/77 do Shotgun (R$ 0–60); atrações em 26 eventos; `organizador` do
Shotgun preenchido.

### FTS com descrição — decisão: LIGADO

- A/B na base real: "eletrônica OR eletrônico" passou de ~3 acertos (nome) para
  **7 eventos** via descrição (Templo, Baile Loco c/ DJ Bassan, Festa 300, Spectres,
  Happy Holi...). "pagode" foi de 8 → 39 resultados, e a revisão a olho mostrou
  recall legítimo (eventos que têm pagode na programação sem a palavra no nome).
- **Ironia registrada:** o caso-âncora (VÉRTICE - House) segue não sendo achado por
  "eletrônica" — a descrição na origem tem **typo**: *"cena **elentronica** de
  Brasília"*. Keyword matching quebra com texto sujo; é mais um argumento pro
  classificador LLM (NI-05). O critério 12 fechou pelos equivalentes.

### Categoria do Sympla — sinal, não regra

O `eventsCategory` matou a cegueira do `'NORMAL'` (agora: `musica`: 196 etc.), mas o
campo é **escolhido pelo organizador e mente**: "The Beatles Abbey Road Tribute" está
em `curso-workshop`, "BAILÃO DO VILLA" em `erotico-adulto-explicito`, piseiro em
`agro`. Portanto **não** virou regra de ruído (mataria show real); fica armazenado
como sinal para o agente e para o ruído v2 (NI-04).

### Calibração de ruído (rodada 2)

- **Adicionado `conference`**: "International Conference of Nanoscience..." passava
  porque a lista era só em português. Base agora com 5 marcados.
- **Novos falsos negativos conhecidos** (sem termo seguro; evidência no NI-04):
  "Atualização em Nódulos de Tireoide" (curso médico), "Open AA", "VIP TÉCNICO BCF",
  "Destravando sua Timidez".

## O que fica para o dogfooding decidir

- Se os limiares de dedupe seguram quando aparecer duplicata real viva.
- Se a lista de ruído precisa de mais termos (rodar
  `python src/atualizar.py --so-enriquecer` após ajustar e revisar o relatório).
- Se o FTS na descrição mantém a precisão em outras consultas de gênero.
- O critério da fase em si (PRD §6): confiar mais no agente do que no Sympla.
