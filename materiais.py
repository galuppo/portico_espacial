"""
Módulo de materiais estruturais do Pórtico Espacial.
"""

from dataclasses import dataclass


@dataclass
class Material:
    """
    Propriedades de um material estrutural (ex.: concreto C30, aço CA-50).

    NÃO é mais frozen: a subclasse Concreto (concreto.py) precisa
    definir atributos próprios (fck, agregado) antes de chamar
    super().__init__() com os valores derivados -- frozen impediria
    isso (object.__setattr__ à parte). Nada no resto do código depende
    de Material ser imutável (nunca é usado como chave de dict/set).
    """

    nome: str
    modulo_elasticidade: float  # E -- unidade consistente com o resto do modelo
    coeficiente_poisson: float
    peso_especifico: float
