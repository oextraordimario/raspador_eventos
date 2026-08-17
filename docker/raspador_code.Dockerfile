# Imagem do serviço `raspador_code` do Dagster no homelab: a code location por
# gRPC e, porque o launcher é o `DefaultRunLauncher`, TAMBÉM quem executa os
# runs. Ou seja: é aqui que o Chromium abre, o Monid roda e a rodada inteira
# acontece. Webserver e daemon continuam magros, com a imagem de
# `homelab/dagster/Dockerfile`.
#
# **Por que este arquivo mora no repo do raspador, e não no `homelab`.** A spec
# (§6.2) previa o contrário — "o Dockerfile do raspador_code é infraestrutura da
# máquina". A execução mostrou que o critério do D5 vale aqui do mesmo jeito: a
# imagem existe para satisfazer o `requirements.txt`, e ele mora aqui. Do lado
# do homelab, `COPY requirements.txt` estaria fora do contexto de build, e as
# saídas eram duplicar o arquivo (defasagem em silêncio — a classe de erro que
# esta spec toda tenta acabar), instalar em runtime a cada `restart`, ou usar
# `additional_contexts`. Dependência nova nasce junto de código novo e os dois
# viajam no MESMO commit, que é exatamente o argumento do `definitions.py`. O
# `docker-compose.yml` — quem DECLARA o serviço — segue no homelab, apontando o
# `context` para o clone.
#
# Só o `requirements.txt` entra no contexto (ver `.dockerignore` da raiz): o
# CÓDIGO chega por bind mount de `/srv/raspador_eventos`, para que `git pull`
# baste e não seja preciso rebuild a cada commit (D1).
FROM python:3.12-slim

# Mesma versão EXATA do `homelab/dagster/Dockerfile`. O protocolo gRPC entre
# daemon e code location é versionado: divergir aqui dá "location failed to
# load" com erro de serialização, sem relação aparente com o que se mexeu.
# Subir versão = subir NOS DOIS Dockerfiles, no mesmo commit.
ARG DAGSTER_VERSION=1.13.17
ARG DAGSTER_LIBS_VERSION=0.29.17
ARG NODE_MAJOR=22

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# git: o SHA do clone vira metadata de run e o `git pull --ff-only` roda de
#      dentro do container (§6.2) — sem ele, "o que executa pode não ser o que
#      você escreveu" e nada avisa.
# tzdata: sem ele o `TZ=America/Sao_Paulo` do compose não resolve, e o dia
#      local de Brasília (dedupe, slug, janelas) viaja três horas.
# curl/gnupg/ca-certificates: repositório do Node.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        git curl ca-certificates gnupg tzdata \
 && curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
 && apt-get install -y --no-install-recommends nodejs

# Monid: a coleta do Instagram é um subprocess do CLI dele. A CHAVE não entra
# na imagem — mora no config do monid, dentro do volume, e entra uma vez por
# `monid keys add` (§12.0, item 9).
# claude: a extração do flyer roda na ASSINATURA (`claude -p`), e o login é
# interativo e humano — fica para a fatia 5. Aqui só o binário.
RUN npm install -g @monid-ai/cli @anthropic-ai/claude-code \
 && npm cache clean --force

RUN pip install \
        dagster==${DAGSTER_VERSION} \
        dagster-postgres==${DAGSTER_LIBS_VERSION}

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# O navegador vem DEPOIS do pip e pelo próprio playwright instalado, nunca de
# uma imagem-base com Chromium pré-assado: o `requirements.txt` pina piso
# (`playwright>=1.57`), então a versão da lib é resolvida no build e só ela
# sabe de qual navegador precisa. `--with-deps` traz as bibliotecas de sistema.
RUN python -m playwright install --with-deps chromium \
 && apt-get purge -y --auto-remove gnupg \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# O código é montado aqui pelo compose; `PYTHONPATH` e `DAGSTER_HOME` também
# vêm de lá, junto do `env_file` com os segredos.
WORKDIR /opt/raspador
