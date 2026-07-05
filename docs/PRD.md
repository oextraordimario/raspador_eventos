# PRD — Base Unificada de Eventos para Agentes de IA

> **Status:** Prova de conceito (PoC) validada para uma fonte (Sympla), ponta a ponta.
> **Documento:** retroativo — escrito após a primeira sessão de validação, consolidando
> o que foi construído e definindo as próximas duas frentes.
> **Última atualização:** 2026-07-05

---

## 1. Visão

Existe um catálogo enorme e fragmentado de eventos no Brasil, espalhado por
plataformas que não conversam entre si (Sympla, Ingresse, Shotgun e outras).
Descobrir "o que tem pra fazer" exige abrir vários sites, cada um com sua busca
limitada e sem linguagem natural.

A proposta é **raspar os eventos dessas plataformas e unificá-los numa única base
de dados otimizada para consulta por agentes de IA**. O usuário final não usa
filtros: ele pergunta em linguagem natural — *"quais festas de pagode vão ter
neste fim de semana em São Paulo?"* — e um agente (ChatGPT, Claude etc.) consulta
a base e responde com eventos reais, com data, local e link de compra.

## 2. Problema e hipótese de risco

O valor do produto (uma camada de IA sobre eventos) só existe se for possível
**obter os dados de forma confiável e estruturada**. Toda a viabilidade do negócio
depende disso. Por isso a primeira hipótese a testar não é a IA — é a raspagem:

> **Hipótese de risco nº 1:** "É possível extrair, de forma robusta e estruturada,
> o catálogo de eventos dessas plataformas?"

Se a raspagem falhar, o resto não importa. Se funcionar, a camada de IA é
considerada tranquila (é filtro sobre dado limpo).

**Resultado da validação (Sympla):** hipótese confirmada. Ver seção 6.

## 3. Objetivos e não-objetivos

### Escopo do PoC (foco atual)
Deliberadamente estreito, para validar o que interessa antes de generalizar:
- **Cidade:** apenas **Brasília (DF)**. Outras cidades/estados estão fora do escopo
  por ora — não são prioridade e não precisam ser testados.
- **Tipo de evento:** apenas **festas, baladas e afins** (vida noturna / música).
  Outros tipos — cursos, workshops, eventos culturais, corporativos etc. — estão
  fora do escopo por ora e devem ser filtrados na coleta ou na consulta.

> A validação inicial da técnica de raspagem (seção 6) foi feita em São Paulo por
> conveniência de volume; daqui pra frente o alvo é Brasília + festas.

### Objetivos (do PoC)
- Provar que dá pra raspar as três plataformas-alvo (Sympla, Ingresse, Shotgun),
  no recorte de Brasília e de festas/baladas.
- Unificar os eventos num schema único, agnóstico de fonte.
- Fechar o loop com IA de verdade: uma pergunta em linguagem natural retorna
  festas corretas de Brasília.

### Não-objetivos (por ora)
- Outras cidades além de Brasília.
- Outros tipos de evento além de festas/baladas.
- Cobertura 100% do catálogo (o PoC opera com amostras representativas).
- Interface de usuário final / app próprio.
- Compra de ingressos, autenticação de usuários, pagamentos.
- Deduplicação cross-fonte do "mesmo" evento anunciado em duas plataformas
  (registrado como questão em aberto, seção 9).

## 4. Usuários e casos de uso

**Usuário primário no PoC:** o próprio agente de IA, que traduz a intenção do
humano em filtros sobre a base.

Casos de uso que a base precisa atender (todos no recorte Brasília + festas):
- Busca temática dentro de vida noturna: *"festas de pagode"*, *"baladas de
  techno"*, *"sertanejo"*, *"funk"*.
- Janela temporal: *"neste fim de semana"*, *"hoje à noite"*, *"sexta que vem"*.
- Combinações: *"pagode neste fim de semana em Brasília"*.
- (Geolocalização por lat/lon fica disponível para um "perto de mim" futuro, mas
  não é foco enquanto o escopo é uma cidade só.)

## 5. Arquitetura da solução

```
  [ Sympla ]   [ Ingresse ]   [ Shotgun ]
      │             │              │
      ▼             ▼              ▼
  ┌─────────────────────────────────────┐
  │  Raspadores (um por fonte)          │  ← descobrem e chamam a API
  │  descobrir → paginar → normalizar   │     JSON interna de cada site
  └─────────────────────────────────────┘
                    │  schema unificado
                    ▼
  ┌─────────────────────────────────────┐
  │  Base unificada (SQLite → futuro:    │  ← eventos + índice de busca
  │  Postgres) + índice textual (FTS)    │     textual (FTS5)
  └─────────────────────────────────────┘
                    │
                    ▼
  ┌─────────────────────────────────────┐
  │  Camada de acesso p/ IA (MCP server  │  ← expõe a base como ferramenta
  │  ou API HTTP)                        │     consultável pelo agente
  └─────────────────────────────────────┘
                    │
                    ▼
        ChatGPT / Claude / agente próprio
```

### 5.1. A técnica-chave de raspagem

O erro comum é parsear HTML — frágil e quebra a cada mudança de layout. A técnica
adotada é outra: **interceptar a API JSON interna que o próprio front-end do site
consome**. Descobre-se o endpoint uma vez (com um navegador headless capturando o
tráfego XHR) e depois chama-se essa API direto, via HTTP puro, sem navegador.

Vantagens: dado já estruturado, payloads leves (seletor de campos), paginação
nativa, muito mais estável que scraping de HTML. E é o **mesmo padrão para as três
fontes**, o que torna a expansão mecânica.

## 6. O que foi construído e validado (Sympla)

Fatia vertical completa, ponta a ponta:

1. **Descoberta da API interna** (`discover_sympla.py`): navegador headless
   (Playwright) capturou as chamadas reais do front. Endpoint encontrado:
   `https://www.sympla.com.br/api/discovery-bff/search/category-type`
   — retorna JSON paginado `{data, total, limit, page}`, com busca textual (`q`),
   filtros geográficos (`city`/`state`/`location`), seletor de campos (`only`) e
   paginação (`limit`/`page`). Sem autenticação.

2. **Raspador** (`sympla.py`): pagina a API via HTTP puro (sem navegador),
   normaliza cada evento para o schema unificado e filtra eventos futuros.

3. **Base** (`store.py`): SQLite com schema único + índice de busca textual FTS5.

4. **Loop de consulta** (`demo.py`): simula o que o agente faria — traduz a
   intenção em filtros SQL (texto + data + cidade).

### Resultados medidos
- **713 eventos futuros** de São Paulo raspados e gravados em ~15s, via HTTP puro.
- Catálogo total disponível na fonte: **~3.728** eventos (SP).
- Consulta **"pagode"** → retornou eventos reais (*Pagode do Toddy*, *Turma do
  Pagode*), com data, local e URL.
- Consulta **"show/música"** → 10 shows reais (JazzB, Casa de Francisca, Café Piu
  Piu...), ordenados por data.

**Conclusão:** o gargalo percebido (raspagem) foi derrubado. Dado estruturado,
limpo e consultável, com técnica replicável.

### 6.1. Schema unificado de eventos

Campos que cada raspador preenche (agnóstico de fonte):

| Campo | Descrição |
|-------|-----------|
| `id` | `<fonte>:<id_nativo>` — chave única cross-fonte |
| `fonte` | `sympla` \| `ingresse` \| `shotgun` |
| `nome` | Nome do evento |
| `start_date` / `end_date` | ISO 8601 |
| `cidade` / `estado` | Localização administrativa |
| `local_nome` / `endereco` / `lat` / `lon` | Local físico |
| `categoria` | Tipo/tema quando disponível |
| `organizador` | Produtor do evento |
| `url` | Link da página de compra |
| `imagem` | Capa do evento |
| `raspado_em` | Timestamp da coleta |

## 7. Roadmap — próximas frentes

### Frente A — Generalizar a raspagem (Ingresse + Shotgun)
Prova que o padrão de "API interna" se sustenta além do Sympla e completa as três
fontes na base unificada.

- **Ingresse:** SPA que consome `api.ingresse.com` (responde 401 — precisa de uma
  `publicKey` embutida no próprio front, extraível). Descobrir endpoint de busca,
  normalizar, gravar.
- **Shotgun (`shotgun.live`):** bloqueia requisições "cara de robô" (retornou 429);
  exige headers realistas e ritmo controlado. Tem API interna própria.
- **Critério de sucesso:** eventos das três fontes convivendo na mesma base, sob o
  mesmo schema, consultáveis pela mesma query.

### Frente B — Fechar o loop com IA de verdade
Hoje `demo.py` *simula* o agente. O passo real é expor a base como uma ferramenta
que um agente consome de fato.

- Expor a base como **MCP server** (consumível direto por Claude/ChatGPT) ou como
  **API HTTP** simples.
- **Critério de sucesso:** perguntar em linguagem natural num cliente de IA real e
  receber eventos corretos da base, sem intermediação manual.

### Frente C — Cobertura e frescor (posterior)
- Paginar o catálogo completo (não só a amostra trending).
- Execução agendada para manter a base atualizada.
- Enriquecer categorias/gênero (o listing não traz o gênero musical; obtido da
  página do evento ou dos temas).

## 8. Métricas de sucesso do PoC

- ✅ Raspagem estruturada funcionando em ≥1 fonte (Sympla — **feito**).
- ⬜ Raspagem funcionando nas 3 fontes sob schema único.
- ⬜ Consulta em linguagem natural via agente de IA real retornando eventos corretos.
- Qualitativo: as respostas do agente batem com o que está realmente à venda nos
  sites (precisão), e cobrem o que deveriam (recall).

## 9. Riscos e questões em aberto

- **Estabilidade das APIs internas:** não são contratos públicos; podem mudar sem
  aviso. Mitigação: raspador tolerante a campos ausentes + monitoramento.
- **Bloqueio / rate-limiting** (visto no Shotgun): exige headers realistas, ritmo
  educado e, se escalar, rotação de IP.
- **Aspecto legal / Termos de Uso:** raspagem de catálogo público versus ToS de
  cada plataforma. A avaliar antes de operação comercial.
- **Deduplicação cross-fonte:** o mesmo evento pode aparecer em duas plataformas;
  ainda não resolvido (fora do escopo do PoC).
- **Frescor vs. custo:** frequência de recoleta que mantém a base útil sem abusar
  das fontes.

## 10. Stack

- **Linguagem:** Python 3.13
- **Descoberta de API:** Playwright (Chromium headless)
- **Raspagem:** HTTP puro (`urllib`, sem dependência de navegador em produção)
- **Base:** SQLite + FTS5 (PoC) → Postgres (produção)
- **Acesso IA:** MCP server ou API HTTP (a definir na Frente B)
