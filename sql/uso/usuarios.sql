-- SCHEMA USO — quem usou. **DADO DE PESSOA**, separado da telemetria de
-- pipeline (operacao) porque tem politica de retencao e de acesso diferente.
--
-- POLITICA DE RECUPERACAO: **NUNCA SE DROPA**; LGPD. Dropar nao quebra o acesso
-- de ninguem — a identidade vive no provedor de login e a tabela se repovoa
-- sozinha no proximo acesso —, mas o historico se perde. Um dump desta tabela
-- contem dado pessoal: fica fora do repositorio e nao vai para lugar nenhum.
--
-- Instrumentacao do MCP remoto (NI-11). Preenchida no PRIMEIRO acesso
-- autenticado (upsert pelo sub do provedor); nao ha cadastro nosso.

CREATE TABLE IF NOT EXISTS usuarios (
    sub        TEXT PRIMARY KEY,  -- id estavel do usuario no IdP (claim `sub` do JWT)
    email      TEXT,              -- claim `email` — e o que torna o registro legivel
    nome       TEXT,
    criado_em  TEXT NOT NULL,     -- ISO UTC "+00:00" — primeiro acesso
    visto_em   TEXT,              -- ISO UTC — ultimo acesso
    bloqueado  INTEGER NOT NULL DEFAULT 0  -- 1 = corta o acesso; reativo, sem allowlist previa
);
