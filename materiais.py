"""
Módulo de materiais estruturais do Pórtico Espacial.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Material:
    """
    Propriedades de um material estrutural (ex.: concreto C30, aço CA-50).

    NOTA: mantido deliberadamente genérico por enquanto -- propriedades
    específicas de concreto armado (fck, agregado, etc., como já usadas
    no projeto sap2000-automation) podem ser adicionadas depois, sem
    quebrar quem já usa Material só com estas propriedades básicas.
    """

    nome: str
    modulo_elasticidade: float  # E -- unidade consistente com o resto do modelo
    coeficiente_poisson: float
    peso_especifico: float
