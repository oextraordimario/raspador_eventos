# Eventos de Brasília

Descobrir o que tem pra fazer hoje à noite em Brasília exige pingar de site em
site — Sympla, Ingresse, Shotgun, Zig, Ticket and Go, Instagram — cada um com sua
busca capenga. Ninguém tem paciência de varrer tudo, então a pessoa vê só um
pedaço do que está rolando e decide no escuro.

Este projeto junta tudo num lugar só: raspa as plataformas de ingresso, a grade
dos cinemas e o Instagram das casas, limpa o resultado (tira anúncio e curso,
junta o mesmo evento publicado em três lugares diferentes, esconde o que foi
cancelado) e entrega isso de duas formas — um **site** pra você abrir no celular
e um **conector** pro seu assistente de IA responder em linguagem natural.

**Cobertura:** só Brasília (DF), e de propósito. Vida noturna (festas, baladas,
shows) e cinema. Uma cidade respondida bem vale mais que dez respondidas pela
metade.

---

## Como usar

### Pelo site

*(em construção — o endereço entra aqui quando estiver no ar)*

Busca por texto, filtros de hoje / fim de semana / próximos 7 dias, festas ou
cinema, só o que é grátis. Cada evento leva pro link de compra na plataforma que
está vendendo. Não vendemos ingresso e não intermediamos nada.

### Pelo seu assistente de IA

O projeto expõe um servidor MCP, que faz o assistente responder coisas como
*"quais festas de pagode tem neste fim de semana?"* ou *"tem alguma animação em
cartaz pra levar criança?"* consultando a base direto, em vez de chutar.

Funciona no Claude, no ChatGPT e em qualquer cliente que fale MCP. O passo a
passo de instalação está em [`docs/TESTE_MCP.md`](docs/TESTE_MCP.md).

---

## De onde vem o dado

| Fonte | O que traz |
|---|---|
| Sympla, Ingresse, Shotgun, Zig, Ticket and Go | festas, baladas e shows à venda |
| Ingresso.com | a grade de 8 cinemas de Brasília |
| Instagram | casas que divulgam só por lá, sem página de venda |

A coleta roda **1x por dia**. Cada evento guarda o link da origem, e o site sempre
manda você comprar na plataforma que está vendendo — a ideia é ser uma vitrine que
direciona tráfego pra elas, não uma cópia do catálogo.

**É uma casa ou plataforma e quer algo removido?** Abra uma
[issue](https://github.com/oextraordimario/raspador_eventos/issues) que a gente
tira.

---

## Rodar localmente

Você não precisa disso pra usar o sistema — só pra desenvolver ou rodar sua
própria cópia.

### O que precisa

- Python 3.12+
- Node.js 20+ (o site e a CLI do Monid)
- Uma base Postgres — o projeto usa [Neon](https://neon.tech) no free tier

### Passo a passo

```bash
git clone https://github.com/oextraordimario/raspador_eventos
cd raspador_eventos

pip install -r requirements.txt
python -m playwright install chromium     # necessário só pro Shotgun
```

Crie um `.env` na raiz (ele é gitignorado) com as connection strings:

```
EVENTOS_DB_URL=postgresql://...          # base principal
EVENTOS_DB_URL_TESTE=postgresql://...    # base descartável, usada pelos testes
```

Aplique o schema rodando [`sql/schema.sql`](sql/schema.sql) na base (DBeaver,
psql, o console do Neon — tanto faz). Depois:

```bash
python src/atualizar.py                  # raspa tudo e popula a base
python src/consulta.py                   # confere que a busca responde
```

A primeira rodada demora ~10 min, a maior parte esperando o Shotgun, que exige
navegador. Pra pular: `python src/atualizar.py --sem-shotgun`.

### Opcional: Instagram

A raspagem do Instagram sai por uma API paga (~US$ 0,006 por perfil por rodada) e
a leitura do flyer usa a CLI do Claude:

```bash
npm i -g @monid-ai/cli
monid keys add -k <sua-chave> -l main    # conta em app.monid.ai
```

Sem isso, use `--sem-instagram` e todo o resto funciona normalmente.

### Testes

Não há framework — são scripts executáveis. Os três primeiros recriam o schema
do zero na base de teste, então exigem internet:

```bash
python tests/test_enriquecer.py
python tests/test_bronze.py
python tests/test_observabilidade.py
python tests/test_cinema.py
python tests/test_zig_ticketandgo.py
python tests/test_instagram.py
python tests/test_mcp_server.py          # exige base já populada
```

---

## Como está organizado

```
src/           núcleo (store, consulta, derivar, enriquecer) + scrapers
  scrapers/    um módulo por fonte, cada um com raspar() → dicts normalizados
api/           entrypoints serverless (MCP remoto e API de leitura do site)
sql/           schema.sql — a fonte única do DDL
dados/         watchlist do Instagram, curada à mão e versionada
docs/          PRD, backlog e specs técnicas
tests/         scripts de fumaça
```

Se você for mexer no código, comece por [`CLAUDE.md`](CLAUDE.md) — ele explica a
arquitetura, as convenções e as armadilhas conhecidas (datas em formatos mistos,
o bug do Bileto, por que o schema é descartável) com bem mais profundidade.

## Licença

[MIT](LICENSE) — a licença cobre o **código**. Os dados raspados pertencem às
plataformas de origem e não são nossos para licenciar.
