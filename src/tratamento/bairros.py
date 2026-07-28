"""Bairro a partir do endereço textual — dado curado à mão, tratamento a seco.

Por que existe: só duas das seis fontes entregam bairro no payload (Sympla e
Zig no `neighborhood`, Shotgun no `addressLocality`), e mesmo elas falham em
metade dos casos. O que sobra é o endereço em texto livre, que na prática
CONTÉM a região — só não num campo.

Onde roda é decisão de arquitetura, não de gosto: dentro da composição do
evento em `comum.aplicar()`, como último passo e SÓ quando `bairro` saiu nulo.
Não em `enriquecer.py`, como o rascunho da spec previa — ali `bairro` ganharia
um SEGUNDO escritor, que é exatamente o desenho que produziu o bug da
`categoria` (uma coluna, dois passos legítimos, quem escreve por último ganha).

Postura: **conservador**. Sem casamento claro, devolve None. Bairro nulo é o
comportamento normal e a faceta só lista o que existe; um bairro errado manda
a pessoa para o outro lado da cidade.

Nota sobre ambiguidade: o CLAUDE.md registra que termos como "Cruzeiro",
"Gama", "Guará" e "Santa Maria" ficam FORA do filtro DF do Ticket and Go, por
casarem com cidades de outros estados. Aqui a situação é outra e o risco não
existe: quando este módulo roda, o evento JÁ foi classificado como de Brasília
— a pergunta não é "é no DF?", é "onde no DF?".
"""

import re
import unicodedata


def _normalizar(texto):
    """Minúsculas, sem acento, com as pontuações viradas espaço."""
    t = unicodedata.normalize("NFD", texto.casefold())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


# (1) Nomes que a pessoa usa para dizer onde fica. A chave é o que se procura
# no endereço normalizado; o valor é a grafia canônica que vai para a base e
# para a faceta — sem isso, "ASA NORTE" e "Asa Norte" virariam dois bairros.
#
# Ordem IMPORTA: o primeiro que casar vence, então o mais específico vem
# antes ("águas claras" antes de "guará" não muda nada, mas "asa sul" precisa
# vir antes de "plano piloto", que é o guarda-chuva de todas as asas).
_NOMES = [
    ("asa sul", "Asa Sul"),
    ("asa norte", "Asa Norte"),
    ("aguas claras", "Águas Claras"),
    ("vicente pires", "Vicente Pires"),
    ("nucleo bandeirante", "Núcleo Bandeirante"),
    ("sao sebastiao", "São Sebastião"),
    ("santa maria", "Santa Maria"),
    ("jardim botanico", "Jardim Botânico"),
    ("recanto das emas", "Recanto das Emas"),
    ("riacho fundo", "Riacho Fundo"),
    ("park way", "Park Way"),
    ("lago sul", "Lago Sul"),
    ("lago norte", "Lago Norte"),
    ("candangolandia", "Candangolândia"),
    ("planaltina", "Planaltina"),
    ("sobradinho", "Sobradinho"),
    ("taguatinga", "Taguatinga"),
    ("ceilandia", "Ceilândia"),
    ("samambaia", "Samambaia"),
    ("brazlandia", "Brazlândia"),
    ("paranoa", "Paranoá"),
    ("sudoeste", "Sudoeste"),
    ("noroeste", "Noroeste"),
    ("octogonal", "Octogonal"),
    ("cruzeiro", "Cruzeiro"),
    ("itapoa", "Itapoã"),
    ("varjao", "Varjão"),
    ("guara", "Guará"),
    ("gama", "Gama"),
    ("eixo monumental", "Eixo Monumental"),
    ("parque da cidade", "Parque da Cidade"),
    # o Sympla escreve o setor por extenso quase tanto quanto pela sigla
    ("clubes esportivos sul", "Setor de Clubes Sul"),
    ("clubes esportivos norte", "Setor de Clubes Norte"),
    ("setor de clubes sul", "Setor de Clubes Sul"),
    ("setor de clubes norte", "Setor de Clubes Norte"),
    # sem a asa, fica genérico mesmo — juntá-lo ao Sul seria inventar o que a
    # fonte não disse
    ("setor de clubes", "Setor de Clubes"),
    ("estrutural", "Estrutural"),
    ("ceilandia", "Ceilândia"),
    ("universitario darcy ribeiro", "UnB"),
    ("campus darcy ribeiro", "UnB"),
]

# (2) Siglas de setor do Plano Piloto. Elas são o endereço REAL de boa parte
# das casas ("SCES Trecho 2", "CLS 413 Bloco B") e não dizem a asa por
# extenso. Aqui a sigla é mais específica que o "Plano Piloto" que costuma
# aparecer na mesma linha, então este passo vem antes daquele.
#
# Só entram siglas de significado inequívoco: as que designam área própria
# (SIA, SAAN, SIG) viram bairro elas mesmas — é assim que a cidade as chama.
_SIGLAS = [
    (r"\bs(?:c|h)es\b", "Setor de Clubes Sul"),
    (r"\bs(?:c|h)en\b", "Setor de Clubes Norte"),
    (r"\bsaan\b", "SAAN"),
    (r"\bsia\b", "SIA"),
    (r"\bsig\b", "SIG"),
    (r"\bsof\b", "SOF"),
    (r"\bsgo\b", "SGO"),
    (r"\bsmas\b", "SMAS"),
    (r"\bsibs\b", "Núcleo Bandeirante"),
    (r"\bsmpw\b", "Park Way"),
    (r"\bsrps\b", "Parque da Cidade"),   # Setor de Recreação Pública Sul
    # blocos residenciais e comerciais: a letra final diz a asa
    (r"\b(?:sqs|shcs|sgas|seps|cls|crs|sds|sbs|scs|epgs)\b", "Asa Sul"),
    (r"\b(?:sqn|shcn|sgan|sepn|cln|crn|scn|epgn)\b", "Asa Norte"),
    (r"\bsres\b", "Cruzeiro"),
]

# (3) Último recurso: o guarda-chuva. Vale mais que nada — "Plano Piloto"
# ainda distingue de Taguatinga —, mas só entra se nada acima casou.
_GENERICO = [("plano piloto", "Plano Piloto")]


# O que a fonte às vezes preenche no campo de bairro e não é bairro nenhum.
_NAO_E_BAIRRO = {"brasilia", "distrito federal", "df", "brasil", "centro"}


def canonizar(bairro):
    """Uniformiza a GRAFIA de um bairro que a fonte já entregou.

    Sem isto a faceta lista "Asa Norte", "ASA NORTE" e "asa norte" como três
    regiões diferentes — e lista mesmo: os três estão na base real, junto com
    "Saan"/"SAAN", "Samambaia norte"/"Samambaia Norte" e "São Sebastião/DF".
    São o mesmo lugar escrito por três produtores diferentes.

    A canonização é o próprio `extrair` aplicado ao valor: se ele reconhecer a
    região, vale a grafia canônica. O que ele não reconhece é PRESERVADO (só
    com espaços e caixa arrumados) — jogar fora seria perder o bairro de
    verdade que só uma fonte informa.
    """
    if not bairro:
        return None
    achado = extrair(bairro)
    if achado:
        return achado
    limpo = re.sub(r"\s+", " ", bairro).strip()
    if not limpo or _normalizar(limpo) in _NAO_E_BAIRRO:
        return None
    # "ESTRUTURAL" e "asa norte" viram capitalizados; o que já vem com caixa
    # mista fica como está (a fonte pode ter escrito "Vila do Boa" de propósito)
    return limpo.title() if limpo.isupper() or limpo.islower() else limpo


def extrair(endereco):
    """Endereço em texto livre → bairro canônico, ou None.

    >>> extrair("CLS 413 Bloco B, 36 - Asa Sul, Brasília - DF")
    'Asa Sul'
    >>> extrair("Sds bloco E loja 3 - SHCS - Plano Piloto, Brasília - DF")
    'Asa Sul'
    >>> extrair("Rua Copaíba") is None
    True
    """
    if not endereco:
        return None
    alvo = _normalizar(endereco)
    if not alvo:
        return None

    for termo, canonico in _NOMES:
        if re.search(rf"\b{re.escape(termo)}\b", alvo):
            return canonico
    for padrao, canonico in _SIGLAS:
        if re.search(padrao, alvo):
            return canonico
    for termo, canonico in _GENERICO:
        if re.search(rf"\b{re.escape(termo)}\b", alvo):
            return canonico
    return None
