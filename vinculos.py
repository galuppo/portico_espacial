"""
Módulo de vínculos (restrições de nó) do Pórtico Espacial.

Restricao é a condição de contorno em si (6 graus de liberdade) --
tipicamente fundação, ou usada para isolar um elemento (ex.: modelar
uma Viga sozinha, com apoios hipotéticos nas extremidades). Para
efetivamente usá-la como apoio de um Lance/Vão/Pilar, ela é envolvida
por ApoioRestricao (elementos.py) -- uma das duas variantes de Apoio,
ao lado de ApoioElemento (apoio em outro elemento real do modelo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .geometria import Ponto


class TipoRestricao(Enum):
    """Tipo de restrição de um grau de liberdade."""

    LIVRE = "livre"
    RESTRINGIDO = "restringido"
    ELASTICO = "elastico"


@dataclass(frozen=True)
class GrauLiberdade:
    """
    Estado de um grau de liberdade (uma translação ou uma rotação).

    `rigidez` só é válida (e obrigatória) quando tipo == ELASTICO --
    verificado em __post_init__ pra evitar estado inconsistente (ex.:
    um grau LIVRE carregando um valor de rigidez que nunca será usado).
    """

    tipo: TipoRestricao = TipoRestricao.LIVRE
    rigidez: float | None = None

    def __post_init__(self) -> None:
        if self.tipo == TipoRestricao.ELASTICO and self.rigidez is None:
            raise ValueError("Grau de liberdade elástico exige um valor de rigidez.")
        if self.tipo != TipoRestricao.ELASTICO and self.rigidez is not None:
            raise ValueError("rigidez só se aplica a um grau de liberdade elástico.")


# Atalhos para os dois estados mais comuns -- evita repetir
# `GrauLiberdade(TipoRestricao.LIVRE)` em cada campo de cada Restricao.
_LIVRE = GrauLiberdade(TipoRestricao.LIVRE)
_RESTRINGIDO = GrauLiberdade(TipoRestricao.RESTRINGIDO)


@dataclass
class Restricao:
    """
    Restrição de um nó, grau de liberdade a grau de liberdade (3
    translações + 3 rotações).

    Pode ser aplicada a qualquer nó do modelo -- não só na base de um
    Pilar (fundação), mas também, por exemplo, nas extremidades de uma
    Viga modelada isoladamente.

    Uso explícito (todos os graus informados um a um):

        Restricao(
            no=algum_ponto,
            translacao_x=GrauLiberdade(TipoRestricao.RESTRINGIDO),
            translacao_z=GrauLiberdade(TipoRestricao.ELASTICO, rigidez=5000.0),
        )

    Uso via métodos de conveniência, para os casos mais comuns: ver
    `engastado`, `apoio_simples` e `elastico_uniforme` abaixo.
    """

    no: Ponto
    translacao_x: GrauLiberdade = field(default_factory=lambda: _LIVRE)
    translacao_y: GrauLiberdade = field(default_factory=lambda: _LIVRE)
    translacao_z: GrauLiberdade = field(default_factory=lambda: _LIVRE)
    rotacao_x: GrauLiberdade = field(default_factory=lambda: _LIVRE)
    rotacao_y: GrauLiberdade = field(default_factory=lambda: _LIVRE)
    rotacao_z: GrauLiberdade = field(default_factory=lambda: _LIVRE)

    @classmethod
    def engastado(cls, no: Ponto) -> "Restricao":
        """Engastamento perfeito: todos os 6 graus de liberdade restringidos."""
        return cls(
            no=no,
            translacao_x=_RESTRINGIDO,
            translacao_y=_RESTRINGIDO,
            translacao_z=_RESTRINGIDO,
            rotacao_x=_RESTRINGIDO,
            rotacao_y=_RESTRINGIDO,
            rotacao_z=_RESTRINGIDO,
        )

    @classmethod
    def apoio_simples(cls, no: Ponto) -> "Restricao":
        """Apoio articulado: as 3 translações restringidas, rotações livres."""
        return cls(
            no=no,
            translacao_x=_RESTRINGIDO,
            translacao_y=_RESTRINGIDO,
            translacao_z=_RESTRINGIDO,
        )

    @classmethod
    def elastico_uniforme(cls, no: Ponto, rigidez_translacao: float) -> "Restricao":
        """
        Aproximação simples de apoio elástico (ex.: solo de fundação):
        as 3 translações com a mesma rigidez, rotações livres.
        """
        mola = GrauLiberdade(TipoRestricao.ELASTICO, rigidez_translacao)
        return cls(no=no, translacao_x=mola, translacao_y=mola, translacao_z=mola)
