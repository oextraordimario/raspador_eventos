# Spec — Rework da página de cinema (NI-35 / NI-36 / NI-37)

> **Status:** especificada em 2026-07-27, aguardando implementação (por
> etapas — ver §7). **O quê/por quê:** feedback de amigos após a abertura do
> site (27/07): a página `/filmes` é uma lista de texto que manda a pessoa
> embora no primeiro clique. O rework a transforma numa vitrine navegável —
> pôster, faixas por categoria (estilo streaming), filtros de verdade e
> detalhe do filme no próprio site. Pedido original do autor em 6 itens,
> mapeados nos NIs: filtros (NI-35), pôster próprio (NI-37), faixas (NI-35),
> sinopse no card (NI-36+NI-35), detalhe/modal (NI-35), nota externa (NI-36).
>
> **Contexto de infra:** domínio cinema é snapshot (spec
> `20260711_raspagem-cinema/`): `cinema_raw` → `aplicar_cinema()` trunca e
> reconstrói `filmes`/`sessoes` a cada rodada. Qualquer dado novo que NÃO
> venha da grade (nota, sinopse externa, pôster re-hospedado) precisa
> sobreviver a essa reconstrução — é a restrição central do design (§4).

---

## 1. O pedido (autor, 2026-07-27)

1. **Filtros:** data (visualização de calendário do mês), gênero (múltipla
   escolha), rede de cinema (Cinemark, Kinoplex...), cinema específico,
   janela de horário de início da sessão, classificação indicativa.
2. **Pôster do filme em cada card** — avaliar raspar e re-hospedar em object
   storage próprio em vez de hotlink.
3. **Faixas por categoria, estilo streaming** (referência: home do Plex) —
   por enquanto com heurísticas simples sobre dados que já existem
   ("populares", "pra toda a família", "pra te tirar o sono"...).
4. **Card:** tirar o número de cinemas; colocar a sinopse.
5. **Clique no filme** abre detalhe no PRÓPRIO site (expansão ou modal) com
   horários das sessões por cinema — não mais direto para a Ingresso.com.
6. **Nota do filme** de IMDb e/ou Letterboxd e/ou TMDB e/ou AdoroCinema.

## 2. Inventário — o que já existe e o que falta

Medido na base real em 2026-07-27 (payload de `cinema_raw` + schema):

| Precisa de | Já existe? | Onde |
|---|---|---|
| Pôster (URL da fonte) | **SIM** | `filmes.poster` (CDN `ingresso-a.akamaihd.net`, tipos `PosterPortrait`/`PosterHorizontal` no payload) — o front simplesmente não usa |
| Gêneros | SIM | `filmes.generos` ("Animação, Aventura, Comédia") |
| Classificação indicativa | SIM | `filmes.classificacao` ("6 anos", "Livre"...) + `ratingDescriptors` no payload (["Violência"...], hoje não derivado) |
| Cinema / horário / sala / tipos / preço / link de compra por sessão | SIM | `sessoes` (via `sessoes_filme()` e `/api/dados/sessoes` — o backend do "modal" já está pronto) |
| Título original | no payload | `originalTitle` — não derivado; é a chave do matching externo (§4.3) |
| Rede do cinema | derivável | prefixo do apelido canônico (§3.1) |
| **Sinopse** | **NÃO** | o payload de sessões não traz `synopsis` (medido: vem `None`) |
| **Nota** | NÃO | nenhuma fonte atual tem |
| **Ano de lançamento** | NÃO | `premiereDate` vem `None` no payload de sessões |

Conclusão que molda a spec: **pedidos 1, 3 e 5 são front + agregação sobre
dados que já existem** (dá pra entregar primeiro); pedidos 4 e 6 dependem de
**fonte nova** (NI-36); pedido 2 depende de **infra de mídia** (NI-37).

## 3. NI-35 — o rework do front

### 3.1 Filtros

Seguem a filosofia do site: **vivem na URL** (`/filmes?data=&generos=&rede=&
cinema=&hora=&class=`), funcionam sem JS, SSR. A `api/dados.py` traduz
querystring para a camada canônica — filtros novos entram em
`consulta.buscar_filmes()` (nunca lógica própria na API).

- **Data (calendário do mês):** honestidade sobre a janela real — a grade
  existe para **~8 dias** (a programação vira na quinta; além disso, só
  pré-venda). O calendário do mês renderiza bonito, mas **dia sem sessão fica
  desabilitado**; dias com grade mostram indicador. Implementação sem
  dependência nova (grid CSS de 7 colunas; `Intl` dá os nomes). Selecionar um
  dia filtra `de/ate` daquele dia local. NÃO raspar mais dias para "encher" o
  mês: seria dado que a fonte não tem.
- **Gênero (múltipla escolha):** `generos` é string CSV — filtro
  `WHERE` com `ILIKE` por termo, OR entre os marcados. A lista de opções sai
  de um `SELECT` distinto na própria API (rota nova `/api/dados/facetas` ou
  campo extra na resposta de `/filmes` — decidir na implementação; a segunda
  evita round-trip).
- **Rede:** derivada do apelido canônico por prefixo — Cinemark, Kinoplex,
  Cinesystem, e os independentes (Cine Brasília, Cine Cultura) como "cinema de
  rua". **Mapa estático em `lib/`** (8 cinemas, dado curado — não vale coluna).
  Filtro vira lista de cinemas → mesmo mecanismo do filtro de cinema.
- **Cinema específico:** já existe (`cinema=` na API); só ganha UI.
- **Janela de horário de início:** filtro sobre `sessoes.inicio` em **hora
  LOCAL de Brasília** (a coluna é UTC — converter na query com o offset -03:00
  fixo, ou comparar sobre `inicio` convertido; NUNCA comparar hora UTC).
  Presets de UI ("matinê < 15h", "noite ≥ 18h", "madrugada") em cima de
  `hora_de`/`hora_ate` genéricos na API.
- **Classificação indicativa:** múltipla escolha sobre `filmes.classificacao`
  (valores distintos da base; são ~6).

Interação filtro × faixas (§3.2): **sem filtro = faixas; com qualquer filtro
= grade plana filtrada** (as faixas são vitrine, não view de busca — é o
comportamento dos streamings e evita faixa com 1 item).

### 3.2 Faixas estilo streaming (heurísticas v1)

Pôster retrato (2:3, como a fonte manda) com scroll horizontal por faixa,
título em cima, nas MESMAS classes de design do site (ZeroUm). Uma chamada
única a `listarFilmes()` já traz tudo; as faixas são **derivadas no front**
(zero backend novo). Heurísticas v1, nesta ordem, filme podendo repetir entre
faixas (como nos streamings):

| Faixa | Regra (dados existentes) |
|---|---|
| Em alta | top N por nº de sessões na janela (é a ordenação atual da consulta) |
| Pra toda a família | `generos` contém Animação/Família OU `classificacao` ∈ {Livre, 6 anos} |
| Pra te tirar o sono | `generos` contém Terror/Suspense |
| Última chance | `ultima_sessao` nos próximos ~2 dias (saindo de cartaz) |
| Pré-venda | `em_pre_venda = 1` |
| Sessão de arte | só passa em Cine Brasília / Cine Cultura (calha de serem os cults) |

Faixa com menos de ~3 filmes não renderiza. Evolução futura (fora desta
spec): faixas por nota (depois do NI-36), "bem avaliados", personalização.

### 3.3 Card

Sai: contagem/lista de cinemas (vai para o detalhe). Entra: pôster (§5) e
**sinopse truncada** (~2 linhas, CSS line-clamp) quando o NI-36 aterrissar —
até lá, gêneros + duração + classificação seguram o card. `tag` de pré-venda
mantida.

### 3.4 Detalhe do filme no próprio site

**Página própria `/filmes/[id]`** (não modal-only): URL compartilhável,
SSR, indexável, JSON-LD `schema.org/Movie` — coerente com a Porta B da Fase 2
e com a decisão dos filtros na URL. No desktop pode abrir em overlay via
intercepting route do App Router (progressive enhancement; a página continua
existindo por baixo). Conteúdo: pôster grande, sinopse inteira, nota (NI-36),
trailer (`filmes.trailer`, já existe), e a grade de sessões **agrupada por
cinema × dia** com horário/sala/tipos/preço — dados prontos em
`/api/dados/sessoes?filme=`. **Cada horário é um link de compra**
(`url_compra`): a postura de ToS não muda — continuamos mandando a venda
para a fonte, só qualificamos o clique antes. O evento de analytics
`film_link_clicked` passa a disparar no clique do horário (o clique que vale).

## 4. NI-36 — sinopse, nota e ano (fonte externa)

### 4.1 Avaliação das fontes pedidas

| Fonte | Viabilidade | Veredito |
|---|---|---|
| **TMDB** | API gratuita (chave por cadastro), ToS ok para uso não comercial **com atribuição**, busca por título, respostas em pt-BR (sinopse!), `vote_average`, ano, pôster de alta qualidade, `external_ids` → `imdb_id` | **primária** |
| IMDb | sem API pública; os datasets oficiais (TSV diários, grátis p/ uso não comercial) têm as notas, mas exigem `tconst` — que o TMDB fornece via `external_ids`. OMDb (terceiro) tem free tier de 1k/dia | **secundária opcional**, via ponte TMDB→imdb_id |
| Letterboxd | API fechada (beta por aprovação) | descartada no v1 |
| AdoroCinema | sem API; seria scraping HTML frágil | descartada no v1 |

**TMDB resolve três pedidos de uma vez** — nota (pedido 6), sinopse em
pt-BR (pedido 4) e ano — e ainda serve de pôster de reserva. Alternativa
avaliada para a sinopse: o endpoint de conteúdo da própria Ingresso.com
(`api-content.ingresso.com/v0/events/...` por filme) — vale 30 min de spike
por consistência com a grade; se render sinopse, o TMDB fica só com
nota/ano. Decidir no spike o que cada um supre.

### 4.2 Onde o dado mora — a restrição do snapshot

`filmes` é truncada e reconstruída a cada rodada; enriquecimento externo NÃO
pode morar só nela (seria re-buscado a cada rodada e some se o TMDB falhar).
Padrão da casa (igual Instagram): **Bronze acumulativa + derivação a seco**:

```sql
-- Bronze do enriquecimento de cinema: 1 payload por filme x origem,
-- INCREMENTAL (só busca filme que ainda nao tem), sobrevive ao snapshot.
CREATE TABLE IF NOT EXISTS cinema_extra_raw (
    filme_id   TEXT NOT NULL,    -- filmes.id (id da Ingresso.com)
    origem     TEXT NOT NULL,    -- 'tmdb' | 'ingresso_evento' | futuro
    payload    TEXT NOT NULL,
    raspado_em TEXT NOT NULL,
    PRIMARY KEY (filme_id, origem)
);
```

Colunas novas em `filmes` (derivadas de `cinema_extra_raw` dentro de
`aplicar_cinema`, depois da reconstrução): `sinopse`, `ano`, `nota`
(0–10, TMDB), `votos`, `tmdb_id`. Schema muda ⇒ **base descartável**
(DROP SCHEMA + re-raspar, convenção do CLAUDE.md). O passo novo no
`atualizar.py` roda após o passo cinema, só para filmes sem linha na Bronze
(o id do filme é estável — 1 chamada por filme NOVO, ~alguns por semana após
o backfill inicial de ~40).

### 4.3 Matching título → TMDB

Chave de busca: `originalTitle` (existe no payload; passa a ser derivado)
com fallback para `titulo`. Sem ano na fonte para desambiguar — mitigação:
preferir o resultado com data de lançamento mais recente ainda ≤ hoje+6 meses
(estamos falando de filmes EM CARTAZ; retrospectiva tipo Cine Cultura pode
casar errado). Guardar o candidato escolhido no payload da Bronze para
auditoria; **na dúvida (score baixo/ambíguo), não gravar nota** — mesmo
princípio conservador do resto do projeto. FTS: a sinopse entra na coluna
`busca` de filmes (reconstruir_fts.sql), como a descrição dos eventos.

## 5. NI-37 — pôster em storage próprio

**Avaliação pedida (hotlink vs re-hospedar):** hotlink do
`ingresso-a.akamaihd.net` funciona hoje, mas (a) CDN alheio pode passar a
exigir referer/expirar caminho sem aviso; (b) republicar imagem quente do CDN
deles em página nossa é mais frágil em ToS do que servir cópia com
atribuição da fonte (mesma discussão do anexo `tos.md`); (c) o NI-34 (mídia
do Instagram, onde a URL **comprovadamente** expira em horas) precisa da
MESMA infra. Veredito: **re-hospedar, numa infra de mídia única para os dois
casos**.

Dimensionamento: ~40 filmes × ~100 KB (webp) ≈ 4 MB + Instagram (~dezenas de
flyers) — irrisório para qualquer free tier. Candidatos, a decidir por spike
de 30 min: **Vercel Blob** (mesma plataforma do site, URL pública, free tier
sobrado para MB) vs **Neon Object Storage** (mesma conta do banco). Critério:
o que tiver upload mais simples a partir do `atualizar.py` local/Actions e
URL pública estável. Fluxo: no passo de derivação/ingestão, para filme (ou
post) novo, baixar a imagem da fonte → subir ao storage → gravar a URL
própria em coluna nova `poster_proprio` (filmes) / `eventos.imagem`
(Instagram, fechando o NI-34 junto). Fallback: sem cópia própria ainda, o
front usa `filmes.poster` (hotlink) — a página não fica esperando a infra.

## 6. Mudanças por camada (resumo)

| Camada | Mudança |
|---|---|
| `sql/schema.sql` | `cinema_extra_raw` nova; `filmes` += `titulo_original`, `sinopse`, `ano`, `nota`, `votos`, `tmdb_id`, `poster_proprio` (⇒ base descartável) |
| `src/scrapers/cinema.py` | intocado (a grade já traz o que precisa) |
| scraper novo `src/scrapers/tmdb.py` (ou função em cinema.py) | busca TMDB por filme novo → Bronze `cinema_extra_raw` |
| `src/derivar.py` | `aplicar_cinema` deriva `titulo_original` e junta `cinema_extra_raw`; sinopse no FTS |
| `src/atualizar.py` | passo incremental "enriquecer cinema" (+ flag `--sem-tmdb` ou similar); upload de mídia (NI-37) |
| `src/consulta.py` | `buscar_filmes` += filtros `generos` (multi), `classificacao` (multi), `hora_de/hora_ate` (hora local), `redes` (via lista de cinemas); resposta += campos novos |
| `api/dados.py` | traduz os params novos; facetas (gêneros/classificações distintos) na resposta |
| `app/filmes/` | faixas, calendário, filtros, card com pôster+sinopse, página `/filmes/[id]` com grade por cinema + JSON-LD Movie |
| MCP (`mcp_server.py`) | **sem tool nova**; `buscar_filmes`/`sessoes_filme` herdam os campos novos de graça (nota/sinopse aparecem no agente sem mudança de contrato) |

## 7. Ordem de implementação (cada etapa entrega valor sozinha)

1. **NI-35a — front com o que já existe:** pôster (hotlink temporário),
   faixas heurísticas, card sem contagem de cinemas, página `/filmes/[id]`
   com a grade de sessões, filtros de cinema/rede/gênero/classificação/
   horário. *(só front + consulta/api; zero schema)*
2. **NI-35b — calendário de data.** *(só front)*
3. **NI-36 — TMDB:** spike de matching (~40 títulos em cartaz) → Bronze +
   derivação + sinopse no card + nota no card/detalhe. *(schema muda 1×)*
4. **NI-37 — storage de mídia:** spike Blob vs Neon → pôster próprio +
   flyer do Instagram (fecha NI-34 junto). *(schema já mudou na etapa 3 —
   coordenar as duas pra dropar a base UMA vez)*

## 8. Plano de teste

- `tests/test_cinema.py` ganha: filtros novos de `buscar_filmes` (gênero
  multi, hora local, classificação), derivação de `titulo_original`,
  snapshot NÃO apaga `cinema_extra_raw`, filme sem nota não quebra consulta.
- Teste novo do matching TMDB com payloads gravados (sem rede, como os
  demais): caso feliz, caso ambíguo (não grava), caso sem resultado.
- `tests/test_api_dados.py`: params novos traduzidos, facetas presentes.
- Visual: conferência manual nos dois temas + mobile (padrão do projeto).

## 9. Riscos e pendências

- **Chave do TMDB**: fica em env (`TMDB_API_KEY` no `.env` local + secret no
  Actions + env na Vercel se a API de leitura precisar — não precisa: a
  leitura só vê a base). Atribuição ao TMDB entra no rodapé/sobre.
- **Matching errado** grava nota de outro filme — mitigado pela regra
  conservadora (§4.3) e auditável pela Bronze.
- **Retrospectivas/cults** (Cine Cultura) são o caso difícil do matching e
  da faixa "Sessão de arte" — aceitar imperfeição no v1.
- **`isReexhibition` e `tags`/`completeTags`** existem no payload e podem
  melhorar as faixas (ex.: "Férias escolares") — anotado, fora do v1.
- O detalhe `/filmes/[id]` muda o funil de clique (site → detalhe → compra,
  um hop a mais). O evento novo de analytics mede se o clique de compra cai.
