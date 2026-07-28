# ⚠️ A RASPAGEM DIÁRIA ESTÁ DESLIGADA

**Desligada em:** 2026-07-28
**Por quê:** migração para a arquitetura medalhão
(`docs/specs/20260728_arquitetura-medalhao/`, §9.8 passo 0).

O workflow `.github/workflows/raspar.yml` foi desativado pela API do GitHub
(`gh workflow disable raspar.yml`), **não** por commit — o arquivo no repo
continua com o `schedule:` intacto.

## Por que ele precisou sair do ar

O banco foi migrado para os schemas novos (`cru`, `tratado`, `curado`,
`operacao`, `uso`), mas o código que faz isso funcionar **ainda não está no
`main` remoto**. O cron roda a partir do `main`. Se ele disparasse agora,
rodaria **código velho contra schema novo** — e a rodada quebraria, ou pior,
escreveria errado.

Não é uma janela de minutos: fica assim até o push.

## Enquanto isso

**Nenhuma raspagem está acontecendo.** A base não envelhece sozinha, mas
também não se atualiza: cada dia parado é um dia de agenda desatualizada no
site e no MCP. Rodadas manuais continuam funcionando normalmente:

```bash
python src/pipeline/atualizar.py --rodada-local
```

## Para religar (a sequência combinada, nesta ordem)

1. Mário confere a implementação localmente
2. Mário dá o ok
3. `git push` do `main`
4. `gh workflow enable raspar.yml`
5. **apagar este arquivo** — ele é o marcador; enquanto existir, o cron está fora

Conferir depois de religar:

```bash
gh workflow list --all      # raspar deve voltar a "active"
gh run list -w raspar.yml   # a próxima rodada é 06:00 UTC (03:00 Brasília)
```
