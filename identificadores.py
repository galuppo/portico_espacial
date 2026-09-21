"""
Modulo de geracao de identificadores do Portico Espacial.

Duas coisas diferentes sao geradas aqui:

  - id: um numero (como string de digitos, ex.: "37"), vindo de UM
    UNICO contador global, compartilhado por TODOS os elementos --
    Pilar, Viga, Laje, e tambem Lance, Vao, Link e barras de grid.
    Sem prefixo, sem relacao com o tipo do elemento, sem relacao
    direta com o nome. E PERMANENTE: uma vez atribuido, nunca e
    reatribuido -- e a chave usada nos dicionarios de
    AnalisePortico/DimensionamentoPortico/DetalhamentoPortico e o
    label na exportacao para a OAPI do SAP2000. Perder essa referencia
    quebraria a rastreabilidade de resultados ja calculados.

  - nome: o rotulo de DOCUMENTACAO (ex.: "P1", "V37"), com prefixo por
    tipo. Para Pilar, e global (um pilar atravessa varios pavimentos,
    entao nao faz sentido reiniciar por andar). Para Viga e Laje,
    reinicia a cada pavimento. Diferente do id, o nome PODE ser
    renovado (ver renovar_nome) -- por isso nome nunca deve ser usado
    como chave/label tecnico, so o id.

A numeracao de Lance/Vao (P1.1, V3.2...) nao passa por aqui -- e uma
property derivada dinamicamente do nome do elemento pai (ver
elementos.py); ja o id de Lance/Vao vem do mesmo contador global de id
usado por Pilar/Viga/Laje.
"""


class GeradorId:
    """Gera o id (numerico, global, permanente) e o nome (com prefixo, por tipo) dos elementos do modelo."""

    def __init__(self) -> None:
        self._proximo_id: int = 1
        self._contadores_nome: dict[str, int] = {}

    def proximo_id(self) -> str:
        """
        Gera o proximo id do contador global unico (ex.: "1", "2",
        "3"...), compartilhado por todo elemento do modelo -- Pilar,
        Viga, Laje, Lance, Vao, Link, barra de grid.
        """
        id_atual = str(self._proximo_id)
        self._proximo_id += 1
        return id_atual

    def proximo_nome(self, prefixo: str, pavimento: str | None = None) -> str:
        """
        Gera o proximo nome de documentacao para um prefixo de tipo
        (ex.: "P" -> "P1", depois "P2").

        Se `pavimento` for informado (Viga, Laje), o contador e
        independente por par (prefixo, pavimento), reiniciando a cada
        pavimento novo. Se `pavimento` for None (Pilar), usa um
        contador global por prefixo.

        `pavimento` e passado como string (o nome do Pavimento, nao o
        objeto) para manter este modulo sem depender de elementos.py.
        """
        chave = prefixo if pavimento is None else f"{prefixo}@{pavimento}"
        self._contadores_nome[chave] = self._contadores_nome.get(chave, 0) + 1
        return f"{prefixo}{self._contadores_nome[chave]}"

    def renovar_nome(self, nome_antigo: str, novo_numero: int, pavimento: str | None = None) -> str:
        """
        Gera um novo NOME para um elemento ja existente (ex.: numa
        revisao de projeto), preservando o prefixo de tipo do nome
        antigo e usando o numero informado explicitamente por quem
        chama.

        Ex.: renovar_nome("V1", 101, pavimento="Terreo") -> "V101".

        O id do elemento NUNCA e afetado por isso -- e permanente (ver
        proximo_id). Reatribuicao simples de nome -- nao guarda
        historico de que "V1" virou "V101"; se isso for necessario
        (rastreabilidade numa revisao), fica por conta de quem chama.

        Atualiza o contador de nome correspondente para o novo numero
        (quando maior que o atual), evitando colisao em geracoes
        futuras de proximo_nome.
        """
        prefixo = "".join(caractere for caractere in nome_antigo if not caractere.isdigit())
        chave = prefixo if pavimento is None else f"{prefixo}@{pavimento}"
        self._contadores_nome[chave] = max(self._contadores_nome.get(chave, 0), novo_numero)
        return f"{prefixo}{novo_numero}"
