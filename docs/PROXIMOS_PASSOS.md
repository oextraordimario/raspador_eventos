# Próximos passos

Backlog de ideias para retomar numa próxima sessão. Registrado em 2026-07-05,
com o PoC no estado: raspagem das 3 fontes (Sympla, Ingresse, Shotgun) →
base unificada SQLite (Brasília + festas) → consultável por agente de IA via MCP,
com conexão validada em Claude Code, Claude Desktop e Codex.

Ordem sugerida (do mais valioso / menor esforço para o mais estrutural):

## 1. Qualidade das respostas do agente (Frente B — item em aberto)
Único ponto que ficou pendente na Frente B: até agora só se validou a **conexão**
do MCP, não a **qualidade**. Testar precisão/recall de verdade fazendo perguntas em
linguagem natural nos clientes e conferindo se:
- as respostas batem com o que está realmente à venda nos sites (precisão);
- não deixam de fora eventos que deveriam aparecer (recall);
- o filtro de data ("hoje", "neste fim de semana") funciona via a tool `data_atual`.

## 2. Apertar o filtro e classificar gênero
O filtro `themes=99` do Sympla ("Festas e Shows") ainda deixa **ruído** passar —
vistos na base: anúncios (ex.: "Conecte-se com a Melhor Banda Larga"), cursos,
conferências. Melhorias:
- ~~apertar o filtro na coleta~~ **feito na Fase 0** (2026-07-09): filtro de
  ruído v1 por palavra-chave em `src/enriquecer.py` (marca `ruido=1`, a consulta
  esconde). A API do Sympla não oferece campo de categoria mais rico (verificado:
  `event_type` é `'NORMAL'` em 100% do catálogo), então a regra opera no nome.
- adicionar um campo de **gênero** (pagode / funk / techno / sertanejo / rock...)
  — hoje a busca depende da palavra estar no nome do evento. Um campo próprio
  melhora direto a precisão das respostas do agente. Fica para a etapa de
  enriquecimento por LLM (v2, junto do Instagram — ver PRD §3).

## 3. Cobertura e frescor (Frente C)
- ~~Paginar o **catálogo completo** de cada fonte~~ **feito na Fase 0**
  (2026-07-09): Sympla esgota o catálogo (a paginação trending cobre 100% dos
  ids); Ingresse já cobria (`total_pages`); Shotgun agora pagina a listagem da
  cidade via `?page=N` até esgotar (antes só a página 1 com scroll → horizonte
  de 3 dias; o catálogo real tinha ~77 eventos até setembro).
- **Re-raspagem agendada** para manter a base atualizada — é a automação via
  GitHub Actions da **Fase 1** (na Fase 0 é sob demanda: `python src/atualizar.py`).
- ~~**Deduplicação cross-fonte**~~ **feito na Fase 0** (2026-07-09): dedupe v1
  por regras em `src/enriquecer.py` (mesmo dia + nome/local similares, política
  conservadora); a consulta devolve só o canônico, com `outras_urls`.

## 4. Persistência em Postgres (Neon, na Fase 1)
Migrar `src/store.py` de SQLite para **Postgres gerenciado (Neon, free tier)** — trocar o
driver e o SQL (FTS5 → `tsvector`/`pg_trgm`; o `norm_ts` migra junto) e revalidar. É o
**portão de entrada da Fase 1** do MVP: acontece junto com a subida do acesso remoto,
quando a base precisa ficar online. Na Fase 0 o SQLite local segue como store. Ver
`docs/PRD_MVP.md`, seções 6 e 7.

## Qualidade de dados já observada (para tratar no caminho)
- `end_date` inconsistente em algum evento do Sympla (começa em 2025, "termina" em
  2035 — erro na origem). Não afeta consultas que filtram por `start_date`.
- Datas em formatos mistos entre fontes (Sympla/Ingresse `+00:00` vs Shotgun
  `.000Z`) — já tratado com normalização em `src/consulta.py`.
- Shotgun grava o **bairro** em `addressLocality`; a cidade é rotulada pelo
  parâmetro de busca no `src/scrapers/shotgun.py`.
