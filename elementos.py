"""
Módulo de elementos estruturais do Pórtico Espacial.

Hierarquia geral:

    ElementoEstrutural (ABC)  -- protocolo comum: todo elemento sabe
    │                            retornar as Barras atômicas que o compõem
    │
    ├── Barra (ABC)            -- elemento geométrico atômico: 2 nós,
    │    │                        seção, material, rotação
    │    ├── Vao                -- trecho de uma Viga entre dois apoios
    │    ├── Lance               -- trecho de um Pilar entre duas quebras
    │    └── Link                -- conector rígido para excentricidade
    │
    ├── Pilar                  -- agregador de Lances (NÃO é uma Barra)
    ├── Viga                   -- agregador de Vãos (NÃO é uma Barra)
    └── Laje                   -- agregadora de barras de grid (NÃO é uma Barra)

Nenhuma classe deste módulo conhece o SAP2000 -- a tradução pra OAPI
fica isolada em exportadores/sap2000.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Union

from .geometria import Ponto
from .grelha import Grelha
from .materiais import Material
from .secoes import SecaoTransversal
from .vinculos import Restricao


class ElementoEstrutural(ABC):
    """
    Protocolo comum a todo elemento do modelo, atômico ou composto.

    Permite ao ModeloPortico tratar Pilar, Viga, Laje e Barra de forma
    uniforme (ex.: `for barra in elemento.barras(): ...`) sem precisar
    saber se por trás existe uma única Barra ou uma lista de Lances/Vãos.
    """

    @abstractmethod
    def barras(self) -> list["Barra"]:
        """Retorna a lista de Barras atômicas que compõem este elemento."""


@dataclass(kw_only=True)
class Barra(ElementoEstrutural):
    """
    Elemento geométrico atômico: um segmento reto entre dois nós, com
    seção transversal, material e rotação próprios.

    É a unidade que efetivamente vira um "frame" no SAP2000 -- todo
    elemento composto (Pilar, Viga, Laje) eventualmente se decompõe em
    uma lista de Barras.

    kw_only=True: permite que subclasses (Lance, Vao) adicionem campos
    obrigatórios (sem default) mesmo depois de `rotacao`, que tem
    default -- sem isso, a ordenação de campos do dataclass geraria erro.

    `id` é PERMANENTE e puramente numérico (ex.: "37", sem prefixo de
    tipo) -- assinado uma única vez, a partir de um único contador
    global compartilhado por todo elemento do modelo (ver
    GeradorId.proximo_id), nunca alterado depois. Diferente do `nome`
    de Lance/Vao (ver abaixo), que é uma property derivada do elemento
    pai e pode mudar quando o pai é renomeado.
    """

    id: str
    no_inicial: Ponto
    no_final: Ponto
    secao: SecaoTransversal
    material: Material
    rotacao: float = 0.0  # ângulo em torno do eixo longitudinal da barra, em graus

    def barras(self) -> list["Barra"]:
        # Caso trivial do protocolo: uma Barra é composta só por ela mesma.
        return [self]


@dataclass
class Pavimento:
    """
    Referência de pavimento, usada para organização/documentação
    (detalhamento) -- independente de onde ocorrem as quebras
    geométricas/analíticas de Lance ou Vão.
    """

    nome: str
    elevacao: float  # cota z do pavimento, em coordenadas globais


class Apoio:
    """
    Interface comum para qualquer forma de apoio de uma extremidade
    (Lance.apoio_base/apoio_topo, Vao.apoio_inicial/apoio_final,
    Pilar.apoio_base/apoio_topo).

    Duas variantes concretas, abaixo:
      - ApoioElemento: apoio em OUTRO ELEMENTO real do modelo (Pilar
        ou Viga hoje; Fundacao no futuro, quando essa classe existir).
      - ApoioRestricao: apoio representado como uma condição de
        contorno simplificada (Restricao, 6 graus de liberdade) --
        usado quando o elemento real por trás não está sendo modelado
        explicitamente (fundação não modelada, elemento isolado ou um
        modelo localizado onde um Pilar/Viga vizinho é aproximado por
        uma restrição em vez de modelado por completo).

    Identificado durante a MODELAGEM (interseção entre elementos, ou
    informado diretamente pelo usuário no caso de ApoioRestricao), mas
    só é efetivamente consumido na fase de DetalhamentoPortico -- é lá
    que a informação "isto se apoia naquilo" vira documentação.

    Regra de direção (só relevante para ApoioElemento):
      - Viga x Pilar: direção padrão implícita é "Viga apoiada no
        Pilar" -- atribuída automaticamente na montagem. Sobrescrevível
        explicitamente pro caso inverso (viga de transição sustentando
        um Pilar).
      - Viga x Viga: não há direção implícita possível (duas vigas
        podem se cruzar em planta sem estarem de fato conectadas), mas
        a EXISTÊNCIA da conexão é 100% determinada geometricamente (ver
        interseccao.py) -- só a direção fica para o DetalhamentoPortico.

    Não deve ser instanciada diretamente -- use ApoioElemento ou
    ApoioRestricao.
    """


@dataclass
class ApoioElemento(Apoio):
    """Apoio em outro elemento estrutural real do modelo."""

    elemento: Union["Pilar", "Viga"]  # -> Union["Pilar", "Viga", "Fundacao"] quando Fundacao existir


@dataclass
class ApoioRestricao(Apoio):
    """Apoio representado como condição de contorno simplificada (sem modelar o elemento real por trás)."""

    restricao: Restricao


@dataclass(kw_only=True)
class Lance(Barra):
    """
    Trecho reto de um Pilar, entre duas quebras consecutivas (pavimento
    ou conexão de Viga).

    Pavimento é sempre atribuído explicitamente -- nunca inferido a
    partir do tipo de conexão, pois uma viga intermediária pode ser só
    travamento (sem laje própria), não implicando necessariamente um
    novo pavimento de documentação.

    Não guarda Apoio/Restricao -- isso é responsabilidade do Pilar
    como um todo (ver Pilar.apoio), já que o apoio de um Pilar (seja
    fundação ou viga de transição) é sempre na base do Pilar inteiro,
    nunca numa quebra intermediária entre Lances.

    `id` (herdado de Barra) é permanente. `nome`, por outro lado, é
    calculado dinamicamente a partir do `nome` ATUAL do Pilar pai --
    reflete automaticamente qualquer renovação de nome do Pilar, sem
    precisar de nenhuma atualização em cascata.
    """

    pilar: "Pilar"
    indice: int  # posição do lance dentro do pilar, da base pro topo (1-based)
    pavimento: Pavimento

    @property
    def nome(self) -> str:
        """Nome de documentação (ex.: 'P1.2'), derivado do nome atual do Pilar pai."""
        return f"{self.pilar.nome}.{self.indice}"


class Link(Barra):
    """
    Elemento rígido que conecta o nó de uma Viga (ou barra de grid de
    Laje) ao nó no eixo do Pilar, na cota de interseção.

    Só é criado quando a interseção não cai exatamente sobre o eixo do
    Pilar (excentricidade real). Substitui o que antes seria um "vetor
    de excentricidade" -- a excentricidade passa a ser representada
    fisicamente por este elemento, com seção/material tipicamente muito
    rígidos, em vez de um dado numérico solto.
    """


@dataclass(kw_only=True)
class Vao(Barra):
    """
    Trecho reto de uma Viga entre dois pontos de quebra consecutivos
    (interseção com Pilar, com outra Viga, ou extremidade em balanço).

    apoio_inicial / apoio_final ficam None quando aquela extremidade é
    um balanço (sem apoio). Nas demais, guardam o Apoio (Pilar ou
    Viga) ou a Restricao daquela extremidade -- atribuídos durante a
    montagem do ModeloPortico, mas só efetivamente usados na fase de
    DetalhamentoPortico.

    `id` (herdado de Barra) é permanente. `nome`, por outro lado, é
    calculado dinamicamente a partir do `nome` ATUAL da Viga pai --
    reflete automaticamente qualquer renovação de nome da Viga, sem
    precisar de nenhuma atualização em cascata.
    """

    viga: "Viga"
    indice: int  # posição do vão dentro da viga, do início pro fim (1-based)
    apoio_inicial: Apoio | None = None
    apoio_final: Apoio | None = None

    @property
    def nome(self) -> str:
        """Nome de documentação (ex.: 'V1.2'), derivado do nome atual da Viga pai."""
        return f"{self.viga.nome}.{self.indice}"


@dataclass
class Pilar(ElementoEstrutural):
    """
    Agregador de Lances -- NÃO é uma Barra.

    Amarrado a Pavimentos, não a coordenadas z livres: a base e o topo
    do Pilar são cada um definidos por um Pavimento (já registrado no
    ModeloPortico) + posição em planta (x, y) + um desnível opcional
    (`desnivel_base`/`desnivel_topo`, padrão 0.0) -- a cota real (z) é
    `pavimento.elevacao + desnivel`. `ponto_base`/`ponto_topo` (usados
    por interseccao.py e o resto do código) são properties calculadas
    a partir disso, não campos armazenados.

    Pode ser inclinado (x, y da base diferentes dos do topo). Os
    Lances finais (com suas quebras) só são conhecidos depois da
    montagem do ModeloPortico (ver ModeloPortico.montar): toda
    elevação de Pavimento registrado entre pavimento_base e
    pavimento_topo vira uma quebra automática, além das quebras por
    conexão de Viga.

    `apoio_base` e `apoio_topo` cobrem as duas extremidades do Pilar
    inteiro -- nunca uma quebra intermediária entre Lances. No caso
    comum, `apoio_base` é uma Restricao (fundação) e `apoio_topo` é
    None (o topo do pilar continua pra cima, ou é só o último Lance);
    no caso especial de viga de transição, `apoio_base` pode ser um
    Apoio referenciando a Viga que sustenta o Pilar. `apoio_topo`
    existe principalmente para modelar um Pilar isolado (ex.: com uma
    condição de contorno hipotética no topo). Preenchidos na montagem
    do ModeloPortico (ou informados diretamente pelo usuário, no caso
    de elemento isolado).

    PENDÊNCIA DE PROJETO: seção/material/rotação podem variar por Lance,
    mas o Pilar é lançado como um elemento único por coordenadas -- a API
    para o usuário sobrescrever seção/material/rotação de um lance
    específico (em vez de usar o padrão do Pilar inteiro) ainda não foi
    definida.
    """

    id: str  # numérico, permanente, do contador global único (ex.: "37") -- chave técnica e label no SAP2000
    nome: str  # rótulo de documentação com prefixo (ex.: "P1") -- global, não reinicia por pavimento
    pavimento_base: Pavimento
    x_base: float
    y_base: float
    pavimento_topo: Pavimento
    x_topo: float
    y_topo: float
    secao: SecaoTransversal  # seção "padrão", usada pelos lances salvo sobrescrita futura
    material: Material
    rotacao: float = 0.0
    desnivel_base: float = 0.0  # somado à elevação de pavimento_base para formar o z real
    desnivel_topo: float = 0.0  # idem, para pavimento_topo
    lances: list[Lance] = field(default_factory=list)  # preenchido na montagem
    apoio_base: Apoio | None = None  # preenchido na montagem (ou informado direto, se isolado)
    apoio_topo: Apoio | None = None  # idem -- normalmente None (o pilar segue pra cima)

    @property
    def ponto_base(self) -> Ponto:
        return Ponto(self.x_base, self.y_base, self.pavimento_base.elevacao + self.desnivel_base)

    @property
    def ponto_topo(self) -> Ponto:
        return Ponto(self.x_topo, self.y_topo, self.pavimento_topo.elevacao + self.desnivel_topo)

    def barras(self) -> list[Barra]:
        return list(self.lances)


@dataclass
class Viga(ElementoEstrutural):
    """
    Agregador de Vãos -- NÃO é uma Barra.

    CONVENÇÃO: ponto_inicial/ponto_final (e, por herança, os nós dos
    Vãos) representam o TOPO da seção da viga, não o eixo centroidal
    -- decisão de projeto, para simplificar modelagem/detalhamento e
    viabilizar desníveis de viga em relação ao pavimento (só um ajuste
    de z). O ajuste para eixo centroidal, que ferramentas de análise
    como SAP2000/OpenSees esperam, é feito na exportação
    (exportadores/), não faz parte do modelo interno.

    Lançada por coordenadas (ponto_inicial -> ponto_final); ao cruzar um
    Pilar ou outra Viga, um Apoio é atribuído automaticamente na
    montagem do ModeloPortico, considerando a seção real do elemento
    cruzado -- inclusive a existência da conexão Viga x Viga, que é
    100% determinada geometricamente (não precisa de declaração
    prévia). O Apoio em si só é efetivamente usado na fase de
    DetalhamentoPortico (a direção -- quem se apoia em quem -- também).

    `nome` é numerado por pavimento (ver GeradorId.proximo_nome) -- o
    pavimento usado como referência pra essa numeração é o do
    ponto_inicial da viga, mesmo que ela (por ser inclinada) toque
    outros pavimentos ao longo do seu comprimento.

    `restricoes`: pontos com condição de contorno externa (Restricao),
    em qualquer posição ao longo do eixo (não só nas pontas) --
    posição = distância absoluta a partir de ponto_inicial. Toda
    Restricao gera um nó e uma quebra de Vão ali, mesmo que caia no
    interior de um trecho que, de outra forma, seria um único Vão.
    """

    id: str  # numérico, permanente, do contador global único (ex.: "52") -- chave técnica e label no SAP2000
    nome: str  # rótulo de documentação com prefixo (ex.: "V1") -- reinicia a cada pavimento, ver GeradorId.proximo_nome
    ponto_inicial: Ponto
    ponto_final: Ponto
    secao: SecaoTransversal
    material: Material
    pavimentos: list[Pavimento] = field(default_factory=list)
    # Lista-resumo dos pavimentos que a viga toca; o mapeamento
    # vão -> pavimento específico é derivado automaticamente pela cota
    # de cada vão, comparada à elevação de cada Pavimento.
    restricoes: list[tuple[float, Restricao]] = field(default_factory=list)
    # (distância absoluta a partir de ponto_inicial, Restricao) -- ver docstring
    vaos: list[Vao] = field(default_factory=list)  # preenchido na montagem

    def barras(self) -> list[Barra]:
        return list(self.vaos)


@dataclass
class Bordo:
    """
    Trecho de contorno de Laje sem viga de apoio (aresta livre).

    Única finalidade: descrever, via polilinha, um trecho de contorno
    que o laço de Vigas ao redor da Laje não cobre.
    """

    pontos: list[Ponto]


@dataclass
class Laje(ElementoEstrutural):
    """
    Agregadora de barras de grid -- NÃO é uma Barra.

    O contorno é derivado automaticamente do laço fechado de Vigas ao
    redor; onde não há viga, o trecho de contorno é coberto por um
    Bordo explícito. Seção e material são constantes para a laje
    inteira (sem variação por barra do grid).

    Viga cruzando o INTERIOR da laje (não apenas a borda) não é
    suportado -- deve gerar erro na montagem.

    `nome` é numerado por pavimento (ver GeradorId.proximo_nome),
    usando `pavimento` abaixo como referência -- diferente de Viga, a
    Laje pertence a um único pavimento (não cruza vários).

    As barras do grid não têm `nome` próprio (diferente de Lance/Vao)
    -- só precisam ser identificáveis por sentido (x ou y), por isso
    ficam em duas listas separadas, em vez de um `nome` hierárquico
    por barra.

    O grid em si é gerado por uma instância interna de `Grelha`
    (módulo `grelha.py`, trazido do projeto do usuário) -- na
    montagem, o contorno (laço de Viga/Bordo) vira o `poligono` que a
    Grelha espera, e `direcao_e1`/`espacamento_x`/`espacamento_y` são
    repassados direto pra `Grelha.gerar_grelha()`. `barras_grid_x`/
    `barras_grid_y` são a tradução das barras da Grelha (tuplas de
    pontos crus) para `Barra` do modelo. A instância de Grelha em si
    fica exposta diretamente (`grelha`, público) -- quem precisar de
    algo como área de influência/carregamento (ex.: pra distribuição
    de carga da laje nas vigas de apoio) acessa os métodos da própria
    Grelha; isso fica pra tratar quando chegarmos na parte de cargas.
    """

    id: str  # numérico, permanente, do contador global único (ex.: "60") -- chave técnica e label no SAP2000
    nome: str  # rótulo de documentação com prefixo (ex.: "LJ1") -- reinicia a cada pavimento
    pavimento: Pavimento
    secao: SecaoTransversal  # espessura da laje
    material: Material
    direcao_e1: tuple[float, float, float]  # direção do eixo local "x" da grelha (ver Grelha.__init__)
    contorno: list[Union[Viga, Bordo]] = field(default_factory=list)
    espacamento_x: float = 0.0
    espacamento_y: float = 0.0
    barras_grid_x: list[Barra] = field(default_factory=list)  # preenchido na montagem
    barras_grid_y: list[Barra] = field(default_factory=list)  # preenchido na montagem
    grelha: Grelha | None = None  # instância da Grelha, preenchida na montagem -- acesso direto aos métodos dela

    def barras(self) -> list[Barra]:
        return [*self.barras_grid_x, *self.barras_grid_y]
