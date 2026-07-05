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
- apertar o filtro de categoria na coleta;
- adicionar um campo de **gênero** (pagode / funk / techno / sertanejo / rock...)
  — hoje a busca depende da palavra estar no nome do evento. Um campo próprio
  melhora direto a precisão das respostas do agente.

## 3. Cobertura e frescor (Frente C)
- Paginar o **catálogo completo** de cada fonte (hoje pega só a amostra "trending").
- **Re-raspagem agendada** para manter a base atualizada.
- **Deduplicação cross-fonte**: o mesmo evento pode aparecer em duas plataformas.

## 4. Persistência em Postgres local
Migrar `store.py` de SQLite para Postgres local (sem nuvem por ora). Checklist
detalhado na seção 10.1 do PRD: inicializar o cluster (`initdb`), testar conexão,
migrar o SQL (FTS5 → `tsvector`) e revalidar. Faz mais sentido junto com um acesso
remoto, se/quando a base precisar ficar online.

## Qualidade de dados já observada (para tratar no caminho)
- `end_date` inconsistente em algum evento do Sympla (começa em 2025, "termina" em
  2035 — erro na origem). Não afeta consultas que filtram por `start_date`.
- Datas em formatos mistos entre fontes (Sympla/Ingresse `+00:00` vs Shotgun
  `.000Z`) — já tratado com normalização em `consulta.py`.
- Shotgun grava o **bairro** em `addressLocality`; a cidade é rotulada pelo
  parâmetro de busca no `shotgun.py`.
