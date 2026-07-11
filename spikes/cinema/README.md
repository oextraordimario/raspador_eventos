# Spike: raspagem de cinema (NI-07)

Teste exploratório para responder: **dá pra raspar deterministicamente a programação
da semana dos cinemas de Brasília?** (PRD §2/§6, backlog NI-07)

Objetivo do spike — para cada rede/cinema relevante do DF:

1. Mapear a técnica: API JSON interna? HTML estático? Precisa de navegador (Playwright)?
2. Escrever um probe determinístico que devolva *filmes em cartaz + sessões da semana*.
3. Anotar achados aqui para virar spec em `docs/specs/` depois.

## Alvos (lista do usuário, 2026-07-11)

A API de conteúdo da Ingresso.com (`api-content.ingresso.com/v0`, sem auth) cobre
quase todos de uma vez — cityId de Brasília = **12** (Taguatinga é 113, fora da lista):

| Cinema | Rede | id Ingresso.com | Status |
|--------|------|-----------------|--------|
| Cinemark Iguatemi | Cinemark | 847 | ✅ raspando |
| Cinemark Pier 21 | Cinemark | 128 | ✅ raspando |
| Kinoplex ParkShopping | Kinoplex | 124 | ✅ raspando |
| Kinoplex Pátio Brasil | Kinoplex | 126 | ✅ raspando |
| Kinoplex Boulevard | Kinoplex | 833 | ✅ raspando |
| Cinesystem CasaPark¹ | Cinesystem | 1605 | ✅ raspando |
| Cine Brasília | Box Cultural | 1583 | ✅ raspando (404 = dia sem sessão) |
| Cine Cultura Liberty Mall | Cine Cultura | 1538 | ✅ raspando |

¹ Nome oficial na API: "Cinesystem Caixa Brasília" (naming rights), mas o endereço
(SGCV Lote 22, Guará) confirma que é o cinema do CasaPark. O site da Cinesystem usa
o MESMO id 1605 — a rede vende via Ingresso.com.

## Achados (2026-07-11)

**Veredito: UM scraper determinístico cobre os 8 cinemas.** Rodada de teste:
38 filmes, 1.232 sessões, 8/8 cinemas respondendo. Sem navegador, sem auth.

- Endpoint: `GET /v0/sessions/city/12/theater/{id}?date=YYYY-MM-DD` → JSON com
  filme (título, gêneros, duração, classificação, distribuidora, pôster, trailer,
  tags tipo "Férias escolares"), salas e sessões (horário local ISO com offset,
  tipo 2D/3D/XD/VIP/DUB/LEG, preço, link de checkout).
- **404 = dia sem sessão** (Cine Brasília fecha alguns dias) — tratar como vazio.
- **Janela útil ≈ quinta→quarta**: a programação vira na quinta; dias além da
  próxima quarta só trazem pré-vendas (ex.: A Odisseia estreando 07-16).
  Raspar 7 dias corridos funciona, mas a cauda fica rala até a virada.
- Sessões especiais aparecem como "tipo" da sessão (Cine Inclusivo, Sessão Azul,
  Cine Pets, Cine Crochê) — dado rico, interpretação fica pro agente (mesma
  filosofia dos lotes).
- `id` de sessão é estável dentro do dia (`85780888`), mas sessão de cinema é
  volátil por natureza — modelagem (filme × sessão × sala vs. schema `eventos`)
  fica pra spec do NI-07, como o backlog manda.
- Risco: dependência de um agregador só (Ingresso.com). Mitigado: TODA rede tem
  fallback viável (ver abaixo). Cinépolis (Ceilândia/Taguatinga) NÃO vende via
  Ingresso.com — fora da lista do usuário, ignorado no spike.

## Fallbacks por rede (auditados em 2026-07-11)

Se a Ingresso.com quebrar, cada rede tem canal próprio raspável — **nenhum exige
navegador** (tudo respondeu a HTTP puro com User-Agent de browser):

| Rede | Canal próprio | Técnica | Qualidade |
|------|---------------|---------|-----------|
| Cinemark | `www.cinemark.com.br/cinema/brasilia_pier_21` (e `brasilia_iguatemi_brasilia`) | Next.js RSC, mas o HTML já vem com a programação renderizada (~1,4MB/página) | média (parse de HTML grande) |
| Kinoplex | `/cinema/cidades.php` (JSON: BSB=804; cinemas 24=Boulevard, 13=ParkShopping, 8=Pátio Brasil) + `/cinema/_programacao_detalhes.php?c={id}` | PHP old-school; programação em HTML estruturado (filmes, salas, horários, com data em comentários) | boa |
| Cinesystem | `www.cinesystem.com.br/site-api/programacao/?cine=1605&data=YYYYMMDD` | **JSON limpo** (filme, sala, formato, legenda, horários + link de compra); usa o MESMO id 1605 da Ingresso.com | ótima |
| Cine Brasília | `cinebrasilia.com` (WordPress) | HTML raspável, pouco estruturado; programação nova toda quarta 18h | fraca |
| Cine Cultura | `cinecultura.com.br/programacao/` (WordPress) | HTML bem estruturado por semana ("9 a 15 de JULHO/2026", "SALA 1 - 14h15") | boa |

Observações:
- A API "oficial" antiga da Cinemark morreu: `programacao.xml` → 404,
  `api.cinemark.com.br` → timeout. O portal developers.cinemark.com.br existe,
  mas exige cadastro — o fallback prático é o HTML/RSC do site.
- Checkout da Cinesystem e do Kinoplex aponta pra `checkout.ingresso.com` — as
  redes são clientes da Ingresso.com na venda, o que reforça a fonte primária
  (dado de sessão é o mesmo; só a casca do site muda).

## Estrutura

- `probe_ingresso_com.py` — descoberta: cityId do DF + lista de cinemas da API
- `probe_semana.py` — o probe principal: 8 cinemas × N dias (`--dias`, default 7)
- `capturas/semana.json` — agregado filme → sessões da última rodada
- `capturas/amostra_raw.json` — um payload bruto de referência (schema da API)
- `capturas_resumo.txt` — resumo legível da última rodada

Este spike NÃO integra com `src/` ainda — modelagem (filme × sessão × sala vs. schema
atual) fica pra spec, como manda o backlog.
