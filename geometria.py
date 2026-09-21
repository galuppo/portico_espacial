"""
Módulo de geometria básica do Pórtico Espacial.

Contém apenas o conceito de nó (Ponto). A responsabilidade de deduplicar
pontos coincidentes (por tolerância) fica a cargo do ModeloPortico, na
montagem do modelo -- não é responsabilidade do Ponto em si.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Ponto:
    """
    Nó em coordenadas globais (x, y, z).

    Imutável (frozen) porque um Ponto representa uma posição fixa no
    espaço -- qualquer "movimento" de um elemento deve criar um novo
    Ponto, nunca mutar um existente (evita bugs de referência
    compartilhada entre elementos que apontam pro mesmo nó).
    """

    x: float
    y: float
    z: float
