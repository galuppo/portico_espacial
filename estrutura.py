"""
Módulo de estrutura do Pórtico Espacial: a montagem do modelo geométrico
e a orquestração das 4 fases do fluxo de trabalho (modelagem, análise,
dimensionamento, detalhamento).

DetalhamentoPortico mora em detalhamento.py (não aqui) -- import feito
dentro do método detalhar() do Portico para evitar import circular
(detalhamento.py importa DimensionamentoPortico daqui).

Nenhuma classe deste módulo conhece o SAP2000 -- a exportação fica
isolada em exportadores/sap2000.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .elementos import (
    Apoio,
    ApoioElemento,
    ApoioRestricao,
    Barra,
    Bordo,
    Laje,
    Lance,
    Link,
    Pavimento,
    Pilar,
    Vao,
    Viga,
)
from .geometria import Ponto
from .grelha import Grelha
from .identificadores import GeradorId
from .interseccao import (
    ResultadoIntersecao,
    ResultadoIntersecaoVigaViga,
    detectar_intersecao_viga_pilar,
    detectar_intersecoes_viga_viga_por_pavimento,
)
from .materiais import Material
from .secoes import SecaoTransversal
from .vinculos import Restricao


def _distancia_no_eixo(viga: Viga, ponto: Ponto) -> float:
    """Distância (ao longo do eixo reto da viga) entre ponto_inicial e um ponto que está sobre esse eixo."""
    p0 = viga.ponto_inicial
    return math.dist((p0.x, p0.y, p0.z), (ponto.x, ponto.y, ponto.z))


def _ponto_na_distancia(viga: Viga, distancia: float) -> Ponto:
    """Ponto sobre o eixo da viga a uma certa distância (absoluta) de ponto_inicial."""
    p0, p1 = viga.ponto_inicial, viga.ponto_final
    comprimento = _distancia_no_eixo(viga, p1)
    if comprimento == 0:
        return p0
    t = distancia / comprimento
    return Ponto(
        x=p0.x + t * (p1.x - p0.x),
        y=p0.y + t * (p1.y - p0.y),
        z=p0.z + t * (p1.z - p0.z),
    )


@dataclass
class ModeloPortico:
    """
    Fase de modelagem: agrega Pilares, Vigas e Lajes lançados por
    coordenadas, resolve as interseções entre eles e deriva Lances,
    Vãos, Apoios e Links -- além de deduplicar nós coincidentes (mesmo
    princípio de tolerância já usado na Grelha).

    Os Apoios já são identificados aqui, mas só são efetivamente usados
    na fase de DetalhamentoPortico -- inclusive a direção (quem se
    apoia em quem), que nunca afeta a montagem geométrica, só a
    documentação depois.

    Pavimentos precisam ser criados (ver criar_pavimento) ANTES de
    qualquer Pilar/Viga/Laje -- eles referenciam Pavimentos já
    existentes (ex.: Pilar.pavimento_base). Criar um elemento sem
    nenhum Pavimento registrado levanta erro.

    id é informação INTERNA do modelo -- sempre gerado por aqui (via
    gerador_id), nunca informado pelo usuário. nome pode ser informado
    opcionalmente; se não for, também é gerado automaticamente. Por
    isso a criação de qualquer elemento passa pelos métodos criar_*
    deste módulo, em vez de instanciar Pilar/Viga/Laje/Pavimento
    diretamente.
    """

    pavimentos: list[Pavimento] = field(default_factory=list)
    pilares: list[Pilar] = field(default_factory=list)
    vigas: list[Viga] = field(default_factory=list)
    lajes: list[Laje] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)  # preenchido na montagem
    gerador_id: GeradorId = field(default_factory=GeradorId)

    # Seção/material padrão para todo Link criado na montagem (ex.: uma
    # seção pequena e um material com módulo de elasticidade bem alto,
    # pra aproximar um conector rígido). Precisam estar configurados
    # ANTES de montar() se houver qualquer excentricidade real no
    # modelo -- senão montar() levanta erro na primeira vez que
    # precisar de um Link.
    secao_link: SecaoTransversal | None = None
    material_link: Material | None = None

    _montado: bool = False

    # Dicionários de acesso rápido por nome. Pilar: nome é global, então
    # a chave é só o nome. Viga/Laje: nome reinicia por pavimento, então
    # a chave é (nome do pavimento, nome do elemento) -- para Viga, é o
    # pavimento DE ORIGEM (o que gerou o nome, ver criar_viga), não
    # necessariamente todo pavimento que ela toca (ver vigas_do_pavimento).
    _pilares_por_nome: dict[str, Pilar] = field(default_factory=dict)
    _vigas_por_pavimento_e_nome: dict[tuple[str | None, str], Viga] = field(default_factory=dict)
    _lajes_por_pavimento_e_nome: dict[tuple[str, str], Laje] = field(default_factory=dict)

    def criar_pavimento(self, nome: str, elevacao: float) -> Pavimento:
        """
        Cria e registra um Pavimento no modelo, retornando o objeto
        criado -- é essa referência que Pilar/Viga/Laje vão usar
        depois (ex.: pavimento_base do Pilar). Deve ser chamado antes
        de criar qualquer Pilar/Viga/Laje.
        """
        pavimento = Pavimento(nome=nome, elevacao=elevacao)
        self.pavimentos.append(pavimento)
        return pavimento

    def _validar_ha_pavimentos(self) -> None:
        if not self.pavimentos:
            raise ValueError(
                "Nenhum Pavimento registrado -- chame criar_pavimento() antes de "
                "criar Pilares, Vigas ou Lajes (mesmo para modelar um elemento "
                "isolado, é preciso registrar ao menos um Pavimento, ainda que fictício)."
            )

    def criar_pilar(
        self,
        pavimento_base: Pavimento,
        x_base: float,
        y_base: float,
        pavimento_topo: Pavimento,
        x_topo: float,
        y_topo: float,
        secao: SecaoTransversal,
        material: Material,
        rotacao: float = 0.0,
        desnivel_base: float = 0.0,
        desnivel_topo: float = 0.0,
        nome: str | None = None,
    ) -> Pilar:
        """
        Cria e registra um Pilar no modelo (ainda sem Lances --
        resolvidos em montar()).

        id é sempre gerado internamente pelo gerador_id do modelo --
        nunca informado por quem chama. nome é opcional: se não
        informado, é gerado automaticamente (numeração global, prefixo
        "P").
        """
        self._validar_ha_pavimentos()
        pilar = Pilar(
            id=self.gerador_id.proximo_id(),
            nome=nome if nome is not None else self.gerador_id.proximo_nome("P"),
            pavimento_base=pavimento_base,
            x_base=x_base,
            y_base=y_base,
            pavimento_topo=pavimento_topo,
            x_topo=x_topo,
            y_topo=y_topo,
            secao=secao,
            material=material,
            rotacao=rotacao,
            desnivel_base=desnivel_base,
            desnivel_topo=desnivel_topo,
        )
        self.pilares.append(pilar)
        self._pilares_por_nome[pilar.nome] = pilar
        return pilar

    def criar_viga(
        self,
        ponto_inicial: Ponto,
        ponto_final: Ponto,
        secao: SecaoTransversal,
        material: Material,
        pavimentos: list[Pavimento] | None = None,
        restricoes: list[tuple[float, Restricao]] | None = None,
        nome: str | None = None,
    ) -> Viga:
        """
        Cria e registra uma Viga no modelo (Vaos resolvidos em
        montar()).

        id é sempre gerado internamente. nome é opcional: se não
        informado, é gerado a partir do primeiro Pavimento em
        `pavimentos` (numeração reinicia por pavimento, prefixo "V");
        se `pavimentos` também não for informado (viga isolada sem
        nenhum Pavimento relevante), usa numeração global.

        Cruzamentos Viga x Viga NAO precisam de declaração prévia: a
        existência da conexão é determinada inteiramente pelo teste
        geométrico em interseccao.detectar_intersecao_viga_viga (que
        já considera seção real -- largura e altura de ambas), rodado
        durante montar(). A direção (quem se apoia em quem) fica só
        para o DetalhamentoPortico -- não afeta a montagem geométrica.
        """
        self._validar_ha_pavimentos()
        pavimentos_ = pavimentos if pavimentos is not None else []
        pavimento_para_nome = pavimentos_[0].nome if pavimentos_ else None
        viga = Viga(
            id=self.gerador_id.proximo_id(),
            nome=nome if nome is not None else self.gerador_id.proximo_nome("V", pavimento_para_nome),
            ponto_inicial=ponto_inicial,
            ponto_final=ponto_final,
            secao=secao,
            material=material,
            pavimentos=pavimentos_,
            restricoes=restricoes if restricoes is not None else [],
        )
        self.vigas.append(viga)
        self._vigas_por_pavimento_e_nome[(pavimento_para_nome, viga.nome)] = viga
        return viga

    def criar_laje(
        self,
        pavimento: Pavimento,
        secao: SecaoTransversal,
        material: Material,
        direcao_e1: tuple[float, float, float],
        contorno: list[Viga | Bordo] | None = None,
        espacamento_x: float = 0.0,
        espacamento_y: float = 0.0,
        nome: str | None = None,
    ) -> Laje:
        """
        Cria e registra uma Laje no modelo (contorno/grid resolvidos
        em montar()).

        id é sempre gerado internamente. nome é opcional: se não
        informado, é gerado a partir de `pavimento` (numeração
        reinicia por pavimento, prefixo "LJ").
        """
        self._validar_ha_pavimentos()
        laje = Laje(
            id=self.gerador_id.proximo_id(),
            nome=nome if nome is not None else self.gerador_id.proximo_nome("LJ", pavimento.nome),
            pavimento=pavimento,
            secao=secao,
            material=material,
            direcao_e1=direcao_e1,
            contorno=contorno if contorno is not None else [],
            espacamento_x=espacamento_x,
            espacamento_y=espacamento_y,
        )
        self.lajes.append(laje)
        self._lajes_por_pavimento_e_nome[(pavimento.nome, laje.nome)] = laje
        return laje

    def pilar_por_nome(self, nome: str) -> Pilar:
        """Busca rápida de um Pilar pelo nome (global -- não depende de pavimento)."""
        return self._pilares_por_nome[nome]

    def viga_por_nome(self, pavimento: Pavimento, nome: str) -> Viga:
        """
        Busca rápida de uma Viga pelo par (pavimento, nome).

        `pavimento` aqui precisa ser o pavimento DE ORIGEM da viga (o
        que gerou o nome na criação) -- para uma viga inclinada que
        toca vários pavimentos, os outros não estão indexados aqui
        (ver vigas_do_pavimento para achar por qualquer pavimento
        tocado, não só o de origem).
        """
        return self._vigas_por_pavimento_e_nome[(pavimento.nome, nome)]

    def laje_por_nome(self, pavimento: Pavimento, nome: str) -> Laje:
        """Busca rápida de uma Laje pelo par (pavimento, nome)."""
        return self._lajes_por_pavimento_e_nome[(pavimento.nome, nome)]

    def vigas_do_pavimento(self, pavimento: Pavimento) -> list[Viga]:
        """
        Todas as Vigas que tocam este Pavimento -- verifica a lista
        completa Viga.pavimentos, não só o pavimento de origem do
        nome. Por isso, diferente de viga_por_nome, uma viga inclinada
        que toca vários pavimentos aparece no resultado de todos eles.
        """
        return [viga for viga in self.vigas if pavimento in viga.pavimentos]

    def lajes_do_pavimento(self, pavimento: Pavimento) -> list[Laje]:
        """Todas as Lajes deste Pavimento (Laje pertence a um único pavimento, sem ambiguidade)."""
        return [laje for laje in self.lajes if laje.pavimento == pavimento]

    def _criar_link(self, no1: Ponto, no2: Ponto) -> Link:
        """Cria um Link entre dois nós, usando secao_link/material_link -- levanta erro se não configurados."""
        if self.secao_link is None or self.material_link is None:
            raise ValueError(
                "Uma conexão com excentricidade real foi encontrada, mas "
                "secao_link/material_link não foram configurados no ModeloPortico -- "
                "defina os dois antes de chamar montar()."
            )
        return Link(
            id=self.gerador_id.proximo_id(),
            no_inicial=no1,
            no_final=no2,
            secao=self.secao_link,
            material=self.material_link,
        )

    def _detectar_todas_intersecoes_viga_pilar(self) -> list[tuple[Viga, Pilar, ResultadoIntersecao]]:
        """Testa cada par (Viga, Pilar) do modelo -- O(n×m); sem otimização por pavimento ainda (ver pendências)."""
        resultados: list[tuple[Viga, Pilar, ResultadoIntersecao]] = []
        for pilar in self.pilares:
            for viga in self.vigas:
                resultado = detectar_intersecao_viga_pilar(viga, pilar)
                if resultado is not None:
                    resultados.append((viga, pilar, resultado))
        return resultados

    def _montar_pilares(self, resultados_viga_pilar: list[tuple[Viga, Pilar, ResultadoIntersecao]]) -> None:
        """
        Deriva os Lances de cada Pilar: quebras nas cotas de todo
        Pavimento registrado que cai dentro da altura do pilar, mais
        as cotas de conexão com Vigas. Pavimento de cada Lance = o
        primeiro Pavimento real encontrado subindo a partir do seu
        topo (regra do pé-direito duplo). Cria Link nas conexões com
        excentricidade real.
        """
        resultados_por_pilar: dict[str, list[ResultadoIntersecao]] = {}
        for _viga, pilar, resultado in resultados_viga_pilar:
            resultados_por_pilar.setdefault(pilar.id, []).append(resultado)

        for pilar in self.pilares:
            z_base, z_topo_pilar = pilar.ponto_base.z, pilar.ponto_topo.z
            z_min, z_max = sorted((z_base, z_topo_pilar))
            x, y = pilar.ponto_base.x, pilar.ponto_base.y  # só pilar vertical (único caminho implementado)

            # cota -> Pavimento: extremos do próprio pilar (sempre presentes,
            # mesmo com desnível) + pavimentos registrados estritamente entre eles
            pavimento_por_cota: dict[float, Pavimento] = {z_min: pilar.pavimento_base, z_max: pilar.pavimento_topo}
            for pavimento in self.pavimentos:
                if z_min < pavimento.elevacao < z_max:
                    pavimento_por_cota[pavimento.elevacao] = pavimento

            cotas = set(pavimento_por_cota)
            for resultado in resultados_por_pilar.get(pilar.id, []):
                cotas.add(resultado.ponto_no_hospedeiro.z)
                if resultado.excentricidade != (0.0, 0.0):
                    self.links.append(self._criar_link(resultado.ponto_no_hospedeiro, resultado.ponto_no_dependente))

            cotas_ordenadas = sorted(cotas)

            pilar.lances = []
            for indice, (base, topo) in enumerate(zip(cotas_ordenadas, cotas_ordenadas[1:]), start=1):
                pavimento_lance = pavimento_por_cota.get(topo)
                if pavimento_lance is None:
                    # quebra sem pavimento próprio (ex.: viga de travamento) -- sobe até achar um real
                    candidatos = sorted(c for c in pavimento_por_cota if c >= topo)
                    pavimento_lance = pavimento_por_cota[candidatos[0]]

                pilar.lances.append(
                    Lance(
                        id=self.gerador_id.proximo_id(),
                        no_inicial=Ponto(x, y, base),
                        no_final=Ponto(x, y, topo),
                        secao=pilar.secao,
                        material=pilar.material,
                        rotacao=pilar.rotacao,
                        pilar=pilar,
                        indice=indice,
                        pavimento=pavimento_lance,
                    )
                )

    def _montar_vigas(
        self,
        resultados_viga_pilar: list[tuple[Viga, Pilar, ResultadoIntersecao]],
        resultados_viga_viga: list[tuple[Viga, Viga, ResultadoIntersecaoVigaViga]],
    ) -> None:
        """
        Deriva os Vãos de cada Viga: quebras nos pontos de conexão com
        Pilares, com outras Vigas, e nas posições de Viga.restricoes.
        Sem hierarquia nenhuma em Viga x Viga -- os dois lados só
        recebem um Apoio referenciando um ao outro. Cria Link nas
        conexões Viga x Viga com cotas de referência diferentes
        (excentricidade em Viga x Pilar já foi tratada em
        _montar_pilares, não duplicada aqui).
        """
        apoios_por_viga: dict[str, list[tuple[float, Apoio]]] = {}

        for viga, pilar, resultado in resultados_viga_pilar:
            distancia = _distancia_no_eixo(viga, resultado.ponto_no_dependente)
            apoios_por_viga.setdefault(viga.id, []).append((distancia, ApoioElemento(elemento=pilar)))

        for viga1, viga2, resultado in resultados_viga_viga:
            d1 = _distancia_no_eixo(viga1, resultado.ponto_viga1)
            d2 = _distancia_no_eixo(viga2, resultado.ponto_viga2)
            apoios_por_viga.setdefault(viga1.id, []).append((d1, ApoioElemento(elemento=viga2)))
            apoios_por_viga.setdefault(viga2.id, []).append((d2, ApoioElemento(elemento=viga1)))
            if resultado.precisa_link:
                self.links.append(self._criar_link(resultado.ponto_viga1, resultado.ponto_viga2))

        for viga in self.vigas:
            comprimento = _distancia_no_eixo(viga, viga.ponto_final)

            # 0.0 e comprimento sempre são quebras (início/fim reais da viga);
            # apoio None ali, a menos que outra fonte diga o contrário -- é o balanço.
            quebras: dict[float, Apoio | None] = {0.0: None, comprimento: None}
            for distancia, apoio in apoios_por_viga.get(viga.id, []):
                quebras[distancia] = apoio
            for distancia, restricao in viga.restricoes:
                quebras[distancia] = ApoioRestricao(restricao=restricao)

            distancias_ordenadas = sorted(quebras)

            viga.vaos = []
            for indice, (d_ini, d_fim) in enumerate(zip(distancias_ordenadas, distancias_ordenadas[1:]), start=1):
                viga.vaos.append(
                    Vao(
                        id=self.gerador_id.proximo_id(),
                        no_inicial=_ponto_na_distancia(viga, d_ini),
                        no_final=_ponto_na_distancia(viga, d_fim),
                        secao=viga.secao,
                        material=viga.material,
                        viga=viga,
                        indice=indice,
                        apoio_inicial=quebras[d_ini],
                        apoio_final=quebras[d_fim],
                    )
                )

    def _construir_poligono_laje(self, laje: Laje) -> list[tuple[float, float, float]]:
        """Converte laje.contorno (Viga/Bordo, em ordem) num polígono de vértices únicos, sem repetir cantos compartilhados."""
        poligono: list[tuple[float, float, float]] = []
        for elemento in laje.contorno:
            if isinstance(elemento, Bordo):
                pontos = [(p.x, p.y, p.z) for p in elemento.pontos]
            else:  # Viga
                pontos = [
                    (elemento.ponto_inicial.x, elemento.ponto_inicial.y, elemento.ponto_inicial.z),
                    (elemento.ponto_final.x, elemento.ponto_final.y, elemento.ponto_final.z),
                ]
            for ponto in pontos:
                if not poligono or poligono[-1] != ponto:
                    poligono.append(ponto)
        if len(poligono) > 1 and poligono[0] == poligono[-1]:
            poligono.pop()
        return poligono

    def _montar_lajes(self) -> None:
        """
        Deriva o grid de cada Laje via Grelha: converte o contorno
        (Viga/Bordo) num polígono, gera o grid, e traduz as barras
        cruas da Grelha para Barra do modelo.

        PENDÊNCIA DE PROJETO: validação de Viga cruzando o INTERIOR da
        Laje (deveria gerar erro) ainda não implementada.
        """
        for laje in self.lajes:
            poligono = self._construir_poligono_laje(laje)
            grelha = Grelha(poligono, laje.direcao_e1)
            grelha.gerar_grelha(laje.espacamento_x, laje.espacamento_y)
            laje.grelha = grelha

            laje.barras_grid_x = [
                Barra(
                    id=self.gerador_id.proximo_id(),
                    no_inicial=Ponto(*p1),
                    no_final=Ponto(*p2),
                    secao=laje.secao,
                    material=laje.material,
                )
                for p1, p2 in grelha.barras_x()
            ]
            laje.barras_grid_y = [
                Barra(
                    id=self.gerador_id.proximo_id(),
                    no_inicial=Ponto(*p1),
                    no_final=Ponto(*p2),
                    secao=laje.secao,
                    material=laje.material,
                )
                for p1, p2 in grelha.barras_y()
            ]

    def montar(self) -> None:
        """
        Executa a montagem do modelo, nesta ordem:
          1. Detecta todas as interseções Viga x Pilar e Viga x Viga
             (considerando seção real -- ver interseccao.py).
          2. Deriva os Lances de cada Pilar (_montar_pilares) -- cria
             Link nas conexões com excentricidade real.
          3. Deriva os Vãos de cada Viga (_montar_vigas) -- cria Link
             nas conexões Viga x Viga com cotas de referência
             diferentes.
          4. Deriva o contorno e o grid de cada Laje (_montar_lajes).

        Nenhuma deduplicação de nós separada: os mesmos objetos Ponto
        calculados pela detecção de interseção são reaproveitados dos
        dois lados (hospedeiro e dependente), então não há dois pontos
        "quase iguais" a reconciliar depois.

        PENDÊNCIAS DE PROJETO:
          - interseção com Pilar inclinado (levanta NotImplementedError
            se algum Pilar não-vertical estiver no modelo)
          - Viga rotacionada na interseção Viga x Viga
          - validação de Viga cruzando o interior de uma Laje
        """
        resultados_viga_pilar = self._detectar_todas_intersecoes_viga_pilar()
        resultados_viga_viga = detectar_intersecoes_viga_viga_por_pavimento(self.vigas)

        self._montar_pilares(resultados_viga_pilar)
        self._montar_vigas(resultados_viga_pilar, resultados_viga_viga)
        self._montar_lajes()

        self._montado = True

    def barras(self) -> list[Barra]:
        """Retorna todas as Barras atômicas do modelo já montado (Lances, Vãos, Links, barras de grid)."""
        if not self._montado:
            raise RuntimeError("Chame montar() antes de acessar as barras do modelo.")
        todas: list[Barra] = list(self.links)
        for elemento in (*self.pilares, *self.vigas, *self.lajes):
            todas.extend(elemento.barras())
        return todas


class AnalisePortico:
    """
    Fase de análise: esforços e deslocamentos resultantes, indexados
    pelo id de cada Barra atômica do ModeloPortico.
    """

    def __init__(self, modelo: ModeloPortico) -> None:
        self.modelo = modelo
        self.esforcos: dict[str, object] = {}  # id da Barra -> resultado de esforço (tipo a definir)
        self.deslocamentos: dict[str, object] = {}  # id do nó -> deslocamento (tipo a definir)


class DimensionamentoPortico:
    """
    Fase de dimensionamento: armadura necessária e verificações segundo
    a NBR 6118, indexadas pelo id de cada Barra atômica.
    """

    def __init__(self, analise: AnalisePortico) -> None:
        self.analise = analise
        self.armaduras: dict[str, object] = {}  # id da Barra -> armadura calculada (tipo a definir)


class Portico:
    """
    Orquestrador: coordena o fluxo entre as 4 fases (modelagem, análise,
    dimensionamento, detalhamento). É o único ponto de entrada esperado
    para quem for usar o pacote de fora.
    """

    def __init__(self, modelo: ModeloPortico) -> None:
        self.modelo = modelo
        self.analise: AnalisePortico | None = None
        self.dimensionamento: DimensionamentoPortico | None = None
        self.detalhamento = None  # type: ignore[var-annotated]  -- tipo real: DetalhamentoPortico | None (ver detalhamento.py)

    def analisar(self) -> AnalisePortico:
        """Exporta o modelo para o SAP2000 (via exportadores.sap2000), roda a análise e importa os resultados."""
        raise NotImplementedError

    def dimensionar(self) -> DimensionamentoPortico:
        """A partir da análise já feita, calcula armadura e verificações da NBR 6118."""
        if self.analise is None:
            raise RuntimeError("Chame analisar() antes de dimensionar().")
        raise NotImplementedError

    def detalhar(self) -> "DetalhamentoPortico":
        """A partir do dimensionamento já feito, organiza a documentação por Pavimento e resolve os Apoios."""
        from .detalhamento import DetalhamentoPortico  # import local: evita ciclo com detalhamento.py

        if self.dimensionamento is None:
            raise RuntimeError("Chame dimensionar() antes de detalhar().")
        raise NotImplementedError
