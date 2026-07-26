# Anexo — Postura sobre Termos de Uso (§6.3)

> **Não é parecer jurídico.** É um levantamento técnico e de produto para o autor
> decidir com o quadro na mão. Se em algum momento entrar dinheiro no meio,
> a conversa muda de natureza e pede advogado de verdade.
>
> Anexo da spec `20260726_abrir-ao-publico`. Escrito em 2026-07-26.

---

## 1. Por que a pergunta aparece agora

Nada muda na raspagem. O que muda é o **destino** do dado:

```
hoje:     plataformas → base → agente de IA do autor          (consumo privado)
depois:   plataformas → base → página pública indexável        (republicação)
```

Consumir dado público para uso próprio e republicá-lo numa página aberta são
posturas com exposição diferente — não porque a coleta mudou, mas porque a
segunda é **visível, atribuível e cresce sozinha** (o passo 5 existe justamente
para o Google e os agentes acharem o site).

O `sumido` e o dedupe não protegem aqui: eles cuidam de correção, não de direito.

## 2. O que já é verdade no sistema hoje

Fatos apurados no código, que definem o ponto de partida:

| Fato | Onde | Relevância |
|---|---|---|
| A coleta usa **APIs internas** do front das plataformas, não APIs públicas documentadas | todos os scrapers | não há contrato de API aceito; vale o ToS do site |
| O `User-Agent` é de navegador comum, sem identificar o robô | `sympla.py:67`, `ingresse.py:49`, `zig.py:40`, `ticketandgo.py:48`, `cinema.py:53` | não nos apresentamos; também não nos disfarçamos ativamente de humano além disso |
| Há **pausa entre requisições** | `cinema.py:103`, `ingresse.py:171` etc. | ritmo educado, sem sobrecarregar a origem |
| O **payload bruto é armazenado** (camada Bronze) | `eventos_raw`, `cinema_raw`, `instagram_raw` | armazenamos mais do que exibimos |
| A busca **trunca a descrição em 300 caracteres** | `consulta.py:30` (`DESCRICAO_MAX`) | exibição parcial |
| O `detalhar_evento` devolve a **descrição INTEIRA** | `consulta.py:101` | é aqui que a republicação vira integral |
| O Instagram é coletado por **intermediário pago** (Monid → TikHub) | `instagram.py` | o atrito com o ToS da Meta é do intermediário; o uso do dado é nosso |
| Todo evento guarda a **URL de origem** | `eventos.url` + `outras_urls` | atribuição e link de volta são triviais de fazer |

**A leitura curta:** o sistema já é, por construção, um agregador que manda o
usuário comprar na plataforma de origem. Isso é a posição mais defensável que
existe neste espaço — e ela é acidental, não foi desenhada como postura. A
decisão aqui é basicamente **assumir isso explicitamente ou não**.

## 3. Onde mora o risco de verdade

Vale separar três coisas que costumam ser embaralhadas:

**a) Dado factual** — nome do evento, data, hora, local, preço, se está esgotado.
Fato não é obra protegida. O que a lei brasileira protege (Lei 9.610/98, art. 7º,
XIII) é a **base de dados** quando há originalidade na seleção ou organização —
ou seja, protege *a compilação da plataforma*, não o fato de que tem pagode no
Ordinário na quarta. Copiar a estrutura e a curadoria inteira de um catálogo é
diferente de listar os mesmos fatos que qualquer um lê no site.

**b) Texto autoral** — a descrição do evento é escrita pelo organizador. É obra.
Reproduzir integralmente é o ponto mais frágil de todo o sistema, e é exatamente
o que o `detalhar_evento` faz hoje. Trecho + link é uma postura substancialmente
diferente de cópia integral.

**c) Contrato (ToS)** — proibições de acesso automatizado. É a camada onde a
raspagem em si é discutida, independentemente de direito autoral. Aqui o risco
prático raramente é judicial: é **bloqueio técnico**. O Shotgun já devolveu 429
para HTTP puro; é assim que essa camada costuma se manifestar.

Uma quarta coisa, menor mas real: **dado pessoal**. `organizador` às vezes é
pessoa física ("Fernando Chaves", visto na base hoje), e os perfis do Instagram
da watchlist são pessoas ou negócios identificáveis. Republicar nome de pessoa
natural numa página aberta entra no escopo da LGPD, ainda que o dado seja público
e o interesse legítimo seja defensável. Não é bloqueador; é um campo a considerar
exibir ou não.

## 4. As quatro posturas possíveis

### A — Agregador com atribuição e link de volta *(recomendada)*

Exibe o **fato** (nome, data, local, preço, disponibilidade), sempre com a fonte
visível e o link para comprar na plataforma. Descrição em **trecho**, não
integral, com "ver no Sympla" para o resto. Nada de imagem (já é a decisão do
v1). Sem `robots.txt` bloqueando ninguém, sem esconder a operação.

- **Exposição:** baixa. Você manda tráfego qualificado para quem vende o
  ingresso — o incentivo comercial da plataforma está alinhado com o seu.
- **O que quebra:** nada no produto. Exige mudar o detalhe do evento para trecho
  + link, o que é uma linha de decisão, não refatoração.
- **Risco residual:** bloqueio técnico por volume (mitigado pelo ritmo educado que
  já existe) e mudança de API sem aviso — que já é risco conhecido do PRD §8.
- **Por que recomendo:** é a postura que o sistema já pratica sem ter decidido.
  Formalizá-la custa quase nada e é a diferença entre "vitrine que direciona
  venda" e "cópia do catálogo alheio".

### B — Republicação rica (descrição integral, imagens, tudo)

Melhor experiência: a pessoa não precisa sair do site para entender o evento.

- **Exposição:** a mais alta das quatro. Reproduz texto autoral integralmente e
  (se as imagens voltarem) serve o asset da plataforma. Passa a competir por
  atenção com a origem em vez de alimentá-la.
- **O que ganha:** UX, e páginas mais ricas para o passo 5 (SEO/agentes).
- **Risco:** notificação de takedown é o cenário realista; o desgaste com as
  plataformas é o custo silencioso. Também enfraquece o argumento de "mando
  tráfego para vocês".

### C — Não abrir o site; manter só a porta MCP com login

Nada é republicado publicamente. O dado só chega a quem se autenticou.

- **Exposição:** a menor. Consumo continua sendo privado, só que de mais gente.
- **O que perde:** o público que está te cobrando — que é justamente quem não
  quer instalar connector nenhum. Mata o passo 3 e o 5, e com eles o motivo
  desta spec inteira.
- **Quando faz sentido:** se você quiser esperar a Fase 1 fechar antes de expor
  qualquer superfície pública.

### D — Falar com as plataformas antes

Procurar Sympla/Shotgun/etc. e propor parceria, feed oficial ou permissão.

- **Exposição:** zero, se der certo.
- **Custo real:** tempo e — o problema — **a resposta padrão de jurídico
  corporativo para pergunta desse tipo é "não"**. Perguntar cria um registro
  formal de negativa que hoje não existe. É uma porta que só se abre uma vez.
- **Quando faz sentido:** quando houver tração e você tiver algo a oferecer
  (volume de tráfego direcionado, dado de demanda). Aí a conversa é entre pares.
  Agora, é pedir licença sem ter o que trocar.

## 5. Resumo

| | Exposição | Custo p/ o produto | Serve pra quem te cobrou? |
|---|---|---|---|
| **A** agregador c/ atribuição | baixa | quase nenhum | sim |
| **B** republicação rica | alta | nenhum | sim |
| **C** só MCP com login | mínima | mata o passo 3 e 5 | não |
| **D** pedir permissão antes | zero se aprovado | tempo + risco de "não" formal | depende da resposta |

**Recomendação: A**, com três medidas concretas que decorrem dela:

1. **Descrição em trecho + link** nas páginas públicas, em vez do texto integral
   que o `detalhar_evento` devolve hoje. A tool MCP pode continuar integral — ela
   serve um agente em contexto privado, não uma página indexada.
2. **Fonte sempre visível** no card e no detalhe, com link direto para comprar na
   plataforma. Já está no protótipo aprovado.
3. **Uma página "sobre"** dizendo em português claro o que o site é, de onde vem o
   dado, que não vendemos ingresso e como uma casa ou plataforma pede remoção.
   É o que transforma a postura em algo verificável por quem chegar reclamando —
   e é barato.

Uma quarta, se você quiser ser conservador sem custo de produto: **não exibir
`organizador` quando ele for nome de pessoa física**. É o único campo com cara de
dado pessoal na superfície pública.

## 6. O que muda na spec quando você decidir

- Postura escolhida vira linha na §4 (decisões travadas), com data.
- Se for A: a §3 passo 3 ganha "descrição em trecho + link" no escopo do detalhe,
  e a página "sobre" entra na lista de telas.
- O PRD §8 (riscos, item "Legal / Termos de Uso") ganha nota registrando que a
  postura foi decidida e qual é — hoje ele só diz "a avaliar".
