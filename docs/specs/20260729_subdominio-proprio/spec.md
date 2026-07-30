# Spec — subdomínio próprio (`role-bsb.extraordimario.com`)

**Data:** 2026-07-29
**Status:** **fatia 1 executada** em 2026-07-29 (domínio na Vercel, AuthKit,
PostHog). A fatia 2 depende de uma ação manual no cPanel da HostGator — é o
único passo que exige o Mário. O que a execução acrescentou ao plano está na
§8.
**Backlog:** adjacente a NI-63 (Search Console) e **bloqueia parcialmente
NI-66** (sitemap) — ver §7.

---

## 0. O pedido

Sair de `raspador-eventos.vercel.app` para `role-bsb.extraordimario.com`,
subdomínio do domínio pessoal do autor, que hoje serve um WordPress hospedado
na HostGator.

O WordPress não é tocado em nenhum passo. A troca é de **endereço**, não de
hospedagem: o site continua servido pela Vercel, e a HostGator só entra como
provedor de DNS.

---

## 1. Estado medido (não suposto)

Tudo abaixo foi lido em 2026-07-29, não inferido.

### 1.1 DNS de `extraordimario.com`

| item | valor |
|---|---|
| nameservers | `ns924.hostgator.com.br`, `ns925.hostgator.com.br` |
| A da raiz | `162.241.2.122` (compartilhado HostGator) |
| `role-bsb.extraordimario.com` | **NXDOMAIN** — não existe |
| wildcard `*.extraordimario.com` | **não existe** |

Os quatro fatos importam: o DNS é gerenciado na HostGator (não no Registro.br
nem em Cloudflare), o nome-alvo está livre, e não há wildcard que pudesse
capturar a resolução antes do registro novo.

### 1.2 Vercel

Projeto `raspador-eventos`, time `zero-um-sd`. **Zero domínios customizados**
hoje. Envs de produção: `EVENTOS_DB_URL`, `BLOB_READ_WRITE_TOKEN`,
`NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST`, `MCP_RECURSO`,
`AUTHKIT_ISSUER`, `MCP_SEGREDO`. **Não existe `NEXT_PUBLIC_ORIGEM`.**

### 1.3 AuthKit (WorkOS)

Ambiente Staging (`environment_01KYFDJMAJ3Z37MGHCKVM1PFT5`) — é o issuer que
produção usa. Recursos OAuth cadastrados:

```
authkit_oauth_resource_01KYFEA6K44PECWXKS1XC3A305
  uri: https://raspador-eventos.vercel.app/mcp
  isDefault: true
```

Um só, e é o endereço antigo. CORS (`webOrigins`): lista vazia.

### 1.4 PostHog

Projeto `Default project` (529039). **`app_urls` está VAZIO** e
`recording_domains` é `null`.

Isto corrige o que eu havia dito antes de medir: não é "ajustar os Authorized
URLs para o domínio novo", é **configurá-los pela primeira vez**. A tarefa
`add_authorized_domain` segue pendente no onboarding do projeto, com
`session_recording_opt_in: true` e `heatmaps_opt_in: true` ligados — ou seja, o
replay grava, mas o toolbar não abre em nenhum domínio hoje.

---

## 2. Os dois pulos do gato

### 2.1 NÃO criar o subdomínio pelo menu "Subdomínios" do cPanel

É o caminho que o painel oferece primeiro e é o errado. Criar um subdomínio ali
provisiona um **document root no servidor da HostGator e um registro A** para
aquele nome. Um CNAME **não pode coexistir com um A no mesmo nome** (RFC 1034
§3.6.2) — o Zone Editor recusa o CNAME, ou pior, aceita e a resolução fica
dependendo de qual registro responde primeiro.

O caminho certo é **cPanel → Zone Editor → Gerenciar (no `extraordimario.com`)
→ Adicionar Registro**:

| campo | valor |
|---|---|
| Tipo | `CNAME` |
| Nome | `role-bsb` (só o prefixo — o cPanel completa o domínio) |
| Classe | `IN` (default, não mexer) |
| TTL | `14400` (default, não mexer) |
| Valor | `24d42ad8e2fbdc2d.vercel-dns-017.com.` (§2.2) |

Se em algum momento o subdomínio for criado por engano pelo menu errado, o
conserto é apagar o A daquele nome no Zone Editor **antes** de criar o CNAME.

### 2.2 O alvo do CNAME não é `cname.vercel-dns.com` de cor

A Vercel emite um **CNAME por projeto**. O deste projeto, lido de
`vercel domains verify` em 2026-07-29:

```
CNAME  role-bsb  →  24d42ad8e2fbdc2d.vercel-dns-017.com.
```

O ponto final faz parte do valor: denota FQDN absoluto, e alguns editores de
zona o exigem para não concatenar o domínio de novo.

A API devolve `cname.vercel-dns.com.` como alternativa **rank 2** — ainda
funciona, mas o rank 1 é o específico do projeto e é o que deve ser usado. Esse
genérico é o valor que aparece em quase todo tutorial e na memória de qualquer
LLM; usá-lo por hábito não quebra nada hoje, mas é o caminho não preferido.

### 2.3 O que NÃO é risco

- **E-mail.** Os MX vivem na raiz. Um CNAME num subdomínio não os toca.
- **O WordPress.** O A da raiz (`162.241.2.122`) fica intacto.
- **`www`.** Não é tocado.

---

## 3. O que muda no código: nada

Medido, arquivo por arquivo:

| peça | por quê não muda |
|---|---|
| proxy do PostHog (`next.config.mjs:25-27`) | rotas relativas `/ph/*` — acompanham o host sozinhas |
| `posthog.capture()` (3 arquivos) | não referenciam host |
| `uso.acessos` / `uso.usuarios` | chaveados pelo `sub` do AuthKit, não pela URL — o histórico por usuário sobrevive |
| `app/sitemap.js`, `app/robots.js`, `app/llms.txt/route.js`, JSON-LD | todos derivam de `ORIGEM` (`lib/config.js:21`) |
| `vercel.json` | as rewrites são por path, não por host |

A mudança é inteiramente de **configuração**: três envs e três painéis.

### 3.1 Mas `NEXT_PUBLIC_ORIGEM` passa a ser obrigatória

`lib/config.js:21` cai em `VERCEL_PROJECT_PRODUCTION_URL` quando
`NEXT_PUBLIC_ORIGEM` não existe. A regra documentada dessa variável é *"the
shortest production custom domain, or vercel.app domain if no custom domain is
available"*.

Contando:

```
raspador-eventos.vercel.app   → 27 caracteres
role-bsb.extraordimario.com   → 27 caracteres
```

**Empate exato.** A regra não desempata, e o valor que o build receber decide a
URL canônica do sitemap, do `robots.txt`, do `llms.txt` e do JSON-LD de toda
página de evento. Depender disso seria deixar o SEO do site na mão de um
critério de desempate não documentado.

Por isso `NEXT_PUBLIC_ORIGEM` deixa de ser higiene e vira **necessária**.

---

## 4. Ordem de execução

A ordem importa por causa do MCP: se `MCP_RECURSO` mudar antes de o AuthKit
conhecer o endereço novo, o servidor anuncia um recurso para o qual o issuer não
emite token, e toda chamada volta 401.

### Fatia 1 — preparação (nenhum efeito em produção) — ✅ FEITA em 29/07

1. ✅ **Vercel:** `vercel domains add role-bsb.extraordimario.com
   raspador-eventos`. Alvo de CNAME em §2.2.
2. ✅ **AuthKit:** `setAuthkitOauthResources` com **os dois** URIs. A mutation
   **substitui a lista inteira** — mandar só o novo derruba o MCP em produção
   na hora:

   ```json
   {"resources": [
     {"id": "authkit_oauth_resource_01KYFEA6K44PECWXKS1XC3A305",
      "uri": "https://raspador-eventos.vercel.app/mcp", "isDefault": true},
     {"uri": "https://role-bsb.extraordimario.com/mcp"}
   ]}
   ```

   Resultado: o novo entrou como `authkit_oauth_resource_01KYR6VW04HGCDNT9KW32PK45H`,
   com `isDefault: false`. O antigo segue default até a fatia 4.

3. ✅ **PostHog:** `app_urls` preenchido com o subdomínio novo, o `.vercel.app`
   e `http://localhost:1007` (§1.4 — estava vazio).

### Fatia 2 — DNS (manual, no cPanel — só o Mário tem acesso)

4. Criar o CNAME conforme §2.1, com o alvo de §2.2.

### Fatia 3 — verificação — ✅ FEITA em 29/07

5. ✅ `Resolve-DnsName role-bsb.extraordimario.com -Server 8.8.8.8` até
   responder o CNAME. A Vercel verifica sozinha.
6. ✅ **A emissão do certificado NÃO é imediata** — ver §8.4. Se o handshake
   TLS falhar depois de a verificação passar, forçar com
   `vercel certs issue role-bsb.extraordimario.com`. Só depois de
   `curl -o /dev/null -w '%{http_code}' https://…/` devolver 200 é que a fatia
   4 pode começar.

### Fatia 4 — a virada

7. ✅ `NEXT_PUBLIC_ORIGEM=https://role-bsb.extraordimario.com` (Production).
8. `MCP_RECURSO=https://role-bsb.extraordimario.com/mcp` (Production).
9. ✅ Redeploy de produção. Conferido: `/robots.txt`, `/sitemap.xml` e
   `/llms.txt` agora anunciam o domínio novo (antes do redeploy o `robots.txt`
   ainda apontava para o `.vercel.app` — a confirmação empírica da §3.1).
10. Conferir o MCP: `/.well-known/oauth-protected-resource/mcp` deve anunciar o
    recurso novo, e `/mcp` sem token deve responder 401.

### Fatia 5 — fecho — **ADIADA por decisão do autor (29/07)**

O MCP saiu do foco: está dando problema e o público que importa hoje chega
pelo site. Os passos 8, 11, 12 e 14 ficam **congelados** até o MCP voltar à
pauta. Consequência prática: o MCP segue servindo no `.vercel.app`, com
`MCP_RECURSO` antigo, e o AuthKit já conhece os dois URIs — nada quebra.

11. ⏸️ **Redirect do `.vercel.app`** — adiado, e a §8.5 mostra que ele deixou
    de ser urgente: o canonical já colapsa o duplicado. Fazer só quando o MCP
    for reendereçado, porque o redirect atinge `/mcp` junto.
12. ⏸️ Reapontar o connector do MCP no celular — ver §5.1.
13. ✅ **Segue valendo:** Search Console com propriedade nova + sitemap
    (NI-63). Não depende do MCP nem do redirect.
14. ⏸️ Tirar o URI antigo do AuthKit.

---

## 5. Riscos

### 5.1 O connector MCP do celular quebra — e não é só reautenticar

Dois efeitos somados:

- `auth.py:50` valida o JWT com `audience=self.recurso`. Trocado o
  `MCP_RECURSO`, os tokens já emitidos para o audience antigo param de validar.
- O redirect do passo 11 vale para **todo path**, `/mcp` inclusive. Um cliente
  apontado para `raspador-eventos.vercel.app/mcp` passa a receber 308 num
  endpoint onde ele espera JSON.

Ou seja: não basta reautenticar, é preciso **reconfigurar o endereço do
connector**. Fazer isso logo após o passo 11, não depois.

### 5.2 Descontinuidade de série no PostHog

O SDK identifica visitante por cookie de primeira parte, com escopo de domínio.
Todo mundo que já visitou o `.vercel.app` conta como visitante novo. Não há
conserto — só o registro de que a quebra na série é a troca de domínio, não uma
queda de tráfego.

### 5.3 SEO

As URLs indexadas não migram sozinhas. O redirect 308 do passo 11 é o que
transfere o sinal; sem ele o buscador vê duas cópias do mesmo conteúdo.

### 5.4 Rollback

Cada fatia volta sozinha: reverter as duas envs e redeployar devolve o estado
atual em minutos, com o AuthKit ainda conhecendo o URI antigo (por isso o passo
14 é o último). O CNAME pode ficar no ar sem prejuízo.

---

## 6. Checklist

- [x] Domínio adicionado na Vercel, alvo de CNAME anotado
- [x] AuthKit com os dois URIs
- [x] PostHog `app_urls` preenchido
- [x] CNAME criado pelo **Zone Editor** (não pelo menu Subdomínios)
- [x] DNS resolvendo + HTTPS válido (certificado forçado — §8.3)
- [x] `NEXT_PUBLIC_ORIGEM` atualizada + redeploy
- [x] `/robots.txt`, `/sitemap.xml`, `/llms.txt` com o domínio novo
- [x] Canonical do `.vercel.app` apontando para o domínio novo (§8.5)
- [ ] Search Console (NI-63)

Congelados com o MCP (§ fatia 5):

- [ ] ⏸️ `MCP_RECURSO` atualizada + redeploy
- [ ] ⏸️ `/mcp` respondendo 401 sem token e 200 com token novo
- [ ] ⏸️ Redirect do `.vercel.app` ativo
- [ ] ⏸️ Connector do celular reapontado
- [ ] ⏸️ URI antigo removido do AuthKit

---

## 7. Fora de escopo, mas na frente do caminho

Medido no `sitemap.xml` e no `llms.txt` já servidos pelo domínio novo:

- ambos **já estão** no esquema de endereços da spec `20260729_urls-semanticas/`
  (`/cinema`, `/evento/<titulo>-<dia>-<mes>`, `ev.slug`) — nada a corrigir aqui;
- o sitemap traz **125 URLs**: 4 rotas fixas + 121 eventos, e **zero filmes**.

Ou seja, o que sobra é o **NI-66** em sua forma exata: nenhuma página
`/cinema/<slug>` entra no sitemap. Isso **não** bloqueia o passo 13 — o sitemap
está correto, só incompleto. Submetê-lo ao Search Console agora não ensina
endereço errado ao buscador; apenas deixa as páginas de filme fora do índice
até o NI-66 sair.

Ordem sugerida: fazer o passo 13 quando for conveniente e reenviar o sitemap
depois do NI-66.

---

## 8. O que a execução da fatia 1 acrescentou ao plano

### 8.1 `vercel domains inspect` recomenda o registro ERRADO para este caso

O comando devolveu:

```
a) Set the following record on your DNS provider to continue:
   `A role-bsb.extraordimario.com 76.76.21.21` [recommended]
```

É um **A**, e a doc oficial diz que subdomínio se configura com **CNAME** — o A
é para apex. O `inspect` opera sobre o domínio pai (`Name: extraordimario.com`)
e devolve a recomendação do apex, mesmo tendo sido chamado com o subdomínio.
Seguir aquele `[recommended]` teria apontado o subdomínio para um IP de apex.

Quem responde certo é `vercel domains verify`, cujo JSON traz
`recommended.records` já resolvido para o nome pedido:

```json
{"type": "CNAME", "name": "role-bsb", "value": "24d42ad8e2fbdc2d.vercel-dns-017.com."}
```

Regra para a próxima vez: para pegar registro DNS de subdomínio, usar
**`verify`**, não `inspect`.

### 8.2 O `76.76.21.21` também está defasado

No mesmo JSON, `recommended.ipv4` traz `216.198.79.1` / `64.29.17.1` como
**rank 1** e `76.76.21.21` apenas como rank 2. O IP que todo tutorial repete é
o de segunda linha hoje. Não afeta esta troca (é subdomínio, vai de CNAME), mas
vale para o dia em que o apex entrar.

### 8.3 O certificado não sai junto com a verificação — e o sintoma engana

Sequência real: o CNAME propagou, `vercel domains verify` devolveu
`configured-correctly` na hora, **e o HTTPS continuou fora do ar**. O openssl
mostrava `no peer certificate available` com 0 bytes lidos, e `vercel certs ls`
não listava nada.

O sintoma engana porque o site **parece funcionar e depois cair**: em HTTP puro
ele responde 200 e serve a página certa desde o primeiro instante, então quem
digita o endereço sem esquema navega normalmente. Quando o navegador faz o
upgrade automático para HTTPS (padrão no Chrome/Edge), o handshake falha e vira
tela de erro — que se lê como "o site caiu", quando na verdade ele nunca esteve
em HTTPS.

O que resolve é forçar: `vercel certs issue <dominio>`. Emissão em ~13s,
propagação na edge em ~15s, certificado Let's Encrypt de 90 dias.

Duas leituras que economizam tempo na próxima vez:

- **`configured-correctly` fala do DNS, não do TLS.** São dois estados
  diferentes e o CLI não distingue no texto.
- Ao diagnosticar, testar **HTTP e HTTPS separadamente**. HTTP 200 + HTTPS com
  handshake vazio é a assinatura de "DNS certo, certificado ausente" — e afasta
  na hora a hipótese de queda do site.

### 8.5 O canonical já resolve o conteúdo duplicado — o redirect não é urgente

Com `NEXT_PUBLIC_ORIGEM` fixa, `app/layout.jsx:22` (`metadataBase: new
URL(ORIGEM)`) e `:35` (`alternates: { canonical: './' }`) passam a valer para
**qualquer host que sirva o build**. Medido nas duas origens:

```
GET https://raspador-eventos.vercel.app/festas
  → <link rel="canonical" href="https://role-bsb.extraordimario.com/festas">
```

Ou seja, o `.vercel.app` já se declara não-canônico sozinho, em toda página.
Isso desarma o motivo original do passo 11: o duplicate content está coberto
sem redirect nenhum, e sem tocar em `/mcp`.

Limite honesto: o canonical é uma **dica forte** ao buscador, não uma ordem —
o 308 é o que garante. E nenhum dos dois hosts manda `x-robots-tag: noindex`
(ambos são domínio de produção do projeto). Para a fase atual — site recém-aberto,
pouco link externo apontando para o `.vercel.app` — a dica basta. O 308 entra
junto com o reendereçamento do MCP, quando ele voltar à pauta.

### 8.4 O PostHog estava sem authorized URLs

Não era ajuste, era configuração inicial — ver §1.4. Efeito colateral bom: o
toolbar e os filtros de web analytics passam a funcionar, o que não acontecia
em domínio nenhum antes.
