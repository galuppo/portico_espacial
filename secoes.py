"""
Módulo de seções transversais do Pórtico Espacial.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


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
