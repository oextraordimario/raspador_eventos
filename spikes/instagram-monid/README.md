# Spike: Instagram via Monid/TikHub (NI-06)

Teste exploratório para responder: **dá pra puxar o contexto de eventos do Instagram
(posts, stories, mídia, comentários) sem lidar nós mesmos com login wall e bloqueio?**
(backlog NI-06 — "Instagram como fonte de contexto"; pedido do usuário em 2026-07-21)

A dor do NI-06 sempre foi a fragilidade da raspagem direta do Instagram (login wall,
bloqueios, layout volátil). A hipótese deste spike: terceirizar essa briga para uma
**API paga intermediária** — o [Monid](https://app.monid.ai) (CLI `@monid-ai/cli`), que
revende endpoints do provider **TikHub**, os quais devolvem o payload interno do
Instagram já em JSON.

## Veredito (2026-07-21)

**Viável e barato para o caso de uso.** Um `@` de casa/produtora rende, sem navegador e
sem tocar no bloqueio do Instagram:

- **posts** com legenda completa, hashtags, `@menções`, likes, nº de comentários,
  `taken_at`, usuários marcados e **URL de imagem em 1080px** (baixável direto do CDN);
- **stories ativos** (vídeo/imagem) com URL de mídia, `taken_at` e `expiring_at`;
- **comentários** com texto, autor, likes e data;
- **detalhe** de um post por URL (schema GraphQL web, com `display_resources` e o campo
  `upcoming_event` — evento nativo do Instagram, quando a casa usa).

Custo por chamada (cobrança **por call**, não por resultado — a janela inteira vem num
run): posts/stories/comentários **$0,003**, detalhe **$0,0015**. A rodada completa deste
spike (4 chamadas + downloads) custou **~US$ 0,011**.

### O achado que fecha o argumento

A **imagem do post é o flyer do evento** e carrega dado que **nem está na legenda**.
No post "Alquimia Dark" (`DbBctmUi9QD`), o flyer traz **data (25/7)**, **preço (20$)** e
**line-up de DJs** — o preço não aparece no texto. Ou seja: a imagem é insumo direto de
OCR/visão para o classificador (NI-05), não só enfeite.

## O que dá pra puxar, por endpoint

Todos são do provider `tikhub`, via `monid run`, com **query params** (nunca body).

| Endpoint | Param | Preço | Entrega |
|----------|-------|-------|---------|
| `/api/v1/instagram/v2/fetch_user_posts` | `username` | $0,003 | lista de posts (paginado por `pagination_token`) |
| `/api/v1/instagram/v2/fetch_user_stories` | `username` | $0,003 | stories ativos (24h) com URL de mídia |
| `/api/v1/instagram/v1/fetch_post_by_url` | `post_url` | $0,0015 | detalhe de 1 post (schema GraphQL web) |
| `/api/v1/instagram/v2/fetch_post_comments` | `code_or_url` | $0,003 | comentários (`sort_by` recent/popular) |

Existem ainda (vistos no `discover`, não testados): `fetch_user_posts` v1 ($0,0015, mais
barato), `fetch_user_tagged_posts`, `fetch_post_info` v2, `shortcode_to_media_id`.

### Campos úteis de um POST (`fetch_user_posts` → `data.items[]`)

`code` (shortcode → `instagram.com/p/<code>/`) · `caption.text` · `caption.hashtags` ·
`caption.mentions` · `like_count` · `comment_count` · `taken_at` (epoch) ·
`media_type` (1=imagem, 2=vídeo, 8=carrossel) · `is_video` · `image_versions.items[]`
(URLs por resolução, maior = 1080) · `original_width/height` · `tagged_users` ·
`location`/`locations` (vieram nulos aqui) · `music_metadata` · `user` (dados do perfil).

### Campos de um STORY (`fetch_user_stories` → `data.items[]`)

`media_type` · `is_video`/`video_versions[]` (URL do mp4, ex.: 720x1280) ·
`image_versions` (poster) · `taken_at` · `expiring_at` (epoch da expiração 24h) ·
`caption` · e stickers quando existem (`story_link_stickers`, `story_hashtags`,
`story_countdowns` — potencial: link de ingresso e contagem regressiva do evento).
No teste: 3 stories, todos vídeo 720x1280.

### Detalhe (`fetch_post_by_url`)

Schema **web/GraphQL**, diferente da lista: `edge_media_to_caption`, `display_resources`
(480/1080/1350), `edge_media_to_tagged_user`, `edge_media_preview_like/comment`,
`location` e **`upcoming_event`** (veio `null` neste post, mas é o campo nativo de evento
do Instagram — vale conferir em casas que usam o recurso). Traz menos "ruído de app" que
a lista, mas exige 1 chamada por post.

## Limitações / riscos anotados

- **Dependência de fornecedor pago** (Monid → TikHub). Se cair, é fonte de *contexto*,
  não de verdade: NI-06 já nasce com tolerância a falha (perfil não raspou → evento segue
  existindo pela plataforma de ingresso).
- **URLs de mídia expiram** (token no CDN do Instagram, ~horas). Para persistir, baixar
  na hora da ingestão (o probe já baixa) — não guardar a URL.
- **Achar o `@` certo** continua sendo o trabalho humano/heurístico de sempre (o spike
  assume o `@` dado). Casa ↔ evento é o elo do NI-04/NI-06.
- **`location` costuma vir nulo** no payload; o "onde" real mora no flyer (imagem) e no
  texto, reforçando a rota de OCR/visão.
- **Cobrança por call**: `maxItems`/múltiplas queries multiplicam custo. Uma query por
  `@` por rodada; começar pequeno.

## Estrutura

- `probe_monid_instagram.py` — probe determinístico (fire-and-poll via CLI `monid`,
  salva payloads crus e baixa mídia de amostra). Uso:
  `python spikes/instagram-monid/probe_monid_instagram.py --user cultorockbar`
- `capturas/` (gitignored — payloads brutos, regeneráveis):
  - `user_posts_full.json` — catálogo cru de posts (schema de referência)
  - `posts_eventos.json` — só os 3 posts de evento do teste (Substance, Alquimia Dark, gótica 18/07)
  - `stories.json` · `detail.json` · `comments.json` — capturas cruas dos outros endpoints
  - `midias/` — imagens dos posts + poster e vídeo de um story (prova de download)

Pré-requisito: `npm i -g @monid-ai/cli` e `monid keys add -k <api-key> -l main`
(conta em app.monid.ai; a chave fica no config do monid, **não** no repo).

Este spike **não** integra com `src/` — modelagem (post/story/flyer → schema `eventos`,
e o pipeline de OCR/visão do flyer) fica para a spec do NI-06, como manda o backlog.
