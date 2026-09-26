"""
Módulo de seções transversais do Pórtico Espacial.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple


class SecaoTransversal(ABC):
    """
    Interface comum para qualquer seção transversal de Barra.

    Definida como ABC para permitir, no futuro, seções não-retangulares
    (circular, T, I, etc.) sem alterar quem já consome SecaoTransversal
    (Barra, Pilar, Viga, Laje) -- eles dependem só desta interface, nunca
    de uma implementação concreta específica.
    """

    @property
    @abstractmethod
    def area(self) -> float:
        """Área da seção."""

    @property
    @abstractmethod
    def inercia_x(self) -> float:
        """Momento de inércia em torno do eixo local x (eixo forte, por convenção)."""

    @property
    @abstractmethod
    def inercia_y(self) -> float:
        """Momento de inércia em torno do eixo local y (eixo fraco, por convenção)."""

    @property
    @abstractmethod
    def vertices(self) -> List[Tuple[float, float]]:
        """
        Contorno poligonal da seção, no sistema de coordenadas LOCAL da
        própria seção -- x = direção "largura" (associada a inercia_y,
        eixo fraco), y = direção "altura" (associada a inercia_x, eixo
        forte) -- origem no ponto de referência da barra (normalmente o
        centroide da seção), sentido anti-horário. Usado só por quem
        precisa da geometria real (ex.: exportação de sólido extrudado);
        cálculos estruturais usam area/inercia_x/inercia_y diretamente.
        """


@dataclass(frozen=True)
class SecaoRetangular(SecaoTransversal):
    """Seção retangular maciça -- caso mais comum para pilares e vigas de concreto armado."""

    largura: float
    altura: float

    @property
    def area(self) -> float:
        return self.largura * self.altura

    @property
    def inercia_x(self) -> float:
        return (self.largura * self.altura**3) / 12

    @property
    def inercia_y(self) -> float:
        return (self.altura * self.largura**3) / 12

    @property
    def vertices(self) -> List[Tuple[float, float]]:
        # retângulo centrado na origem, sentido anti-horário
        meia_largura, meia_altura = self.largura / 2, self.altura / 2
        return [
            (-meia_largura, -meia_altura),
            (meia_largura, -meia_altura),
            (meia_largura, meia_altura),
            (-meia_largura, meia_altura),
        ]


@dataclass(frozen=True)
class SecaoPoligonal(SecaoTransversal):
    """
    Seção transversal com contorno poligonal arbitrário (T, I, L, circular
    aproximada por N lados etc.) -- área e inércias calculadas
    diretamente do polígono (fórmulas de Green/shoelace), sem depender de
    fórmula fechada por tipo de forma. Suporta qualquer polígono simples
    (não autointerseccionado), em qualquer sentido (a classe normaliza
    internamente pro cálculo) -- não precisa estar centrado na origem:
    area/inercia_x/inercia_y já são computados em torno do centroide real
    do polígono (teorema dos eixos paralelos), independente de onde a
    origem local cai.

    vertices: pelo menos 3 pontos (x, y), sem repetir o primeiro no fim.
    """

    vertices_informados: Tuple[Tuple[float, float], ...]

    def __init__(self, vertices: List[Tuple[float, float]]):
        if len(vertices) < 3:
            raise ValueError("Uma seção poligonal precisa de ao menos 3 vértices.")
        object.__setattr__(self, "vertices_informados", tuple(vertices))

    @property
    def vertices(self) -> List[Tuple[float, float]]:
        return list(self.vertices_informados)

    def _area_com_sinal(self) -> float:
        """Área pela fórmula do shoelace -- positiva se os vértices estiverem em sentido anti-horário."""
        pontos = self.vertices_informados
        soma = 0.0
        for i in range(len(pontos)):
            x_i, y_i = pontos[i]
            x_j, y_j = pontos[(i + 1) % len(pontos)]
            soma += x_i * y_j - x_j * y_i
        return soma / 2

    def _centroide(self) -> Tuple[float, float]:
        pontos = self.vertices_informados
        area_sinal = self._area_com_sinal()
        cx = cy = 0.0
        for i in range(len(pontos)):
            x_i, y_i = pontos[i]
            x_j, y_j = pontos[(i + 1) % len(pontos)]
            termo = x_i * y_j - x_j * y_i
            cx += (x_i + x_j) * termo
            cy += (y_i + y_j) * termo
        fator = 1 / (6 * area_sinal)
        return cx * fator, cy * fator

    def _inercias_na_origem_com_sinal(self) -> Tuple[float, float]:
        """Ix, Iy em torno da ORIGEM local (não do centroide) -- com o mesmo sinal de _area_com_sinal()."""
        pontos = self.vertices_informados
        ix = iy = 0.0
        for i in range(len(pontos)):
            x_i, y_i = pontos[i]
            x_j, y_j = pontos[(i + 1) % len(pontos)]
            termo = x_i * y_j - x_j * y_i
            ix += (y_i**2 + y_i * y_j + y_j**2) * termo
            iy += (x_i**2 + x_i * x_j + x_j**2) * termo
        return ix / 12, iy / 12

    @property
    def area(self) -> float:
        return abs(self._area_com_sinal())

    @property
    def inercia_x(self) -> float:
        area_sinal = self._area_com_sinal()
        ix_origem, _ = self._inercias_na_origem_com_sinal()
        _, cy = self._centroide()
        # teorema dos eixos paralelos, com sinal consistente (cancela se os vértices
        # estiverem em sentido horário -- abs() no final corrige pro valor físico, sempre positivo)
        return abs(ix_origem - area_sinal * cy**2)

    @property
    def inercia_y(self) -> float:
        area_sinal = self._area_com_sinal()
        _, iy_origem = self._inercias_na_origem_com_sinal()
        cx, _ = self._centroide()
        return abs(iy_origem - area_sinal * cx**2)
