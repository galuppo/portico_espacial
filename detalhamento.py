"""
Modulo de detalhamento do Portico Espacial.

Apoio (quem se apoia em quem) e identificado durante a MODELAGEM (ver
elementos.py), atribuido a cada Vao/Lance no ponto de intersecao. Mas
so e efetivamente CONSUMIDO aqui: e o DetalhamentoPortico quem le essa
informacao para organizar a documentacao por Pavimento.

O unico papel deste modulo em relacao ao proprio Apoio e de VALIDACAO:
para todo cruzamento Viga x Viga, verificar se o Apoio foi declarado
explicitamente na modelagem (ver
ModeloPortico.declarar_apoio_viga_em_viga) e informar ou levantar erro
caso nao tenha sido -- ja que, diferente de Viga x Pilar, essa direcao
nunca pode ser inferida automaticamente.
"""

from __future__ import annotations

from .estrutura import DimensionamentoPortico, ModeloPortico


class ApoioNaoDefinidoError(Exception):
    """Levantado quando um cruzamento Viga x Viga não tem Apoio declarado na modelagem."""


class DetalhamentoPortico:
    """
    Fase de detalhamento: organização da documentação por Pavimento e
    listas de ferro, a partir dos Apoios já identificados na modelagem.
    """

    def __init__(self, dimensionamento: DimensionamentoPortico) -> None:
        self.dimensionamento = dimensionamento

    def validar_apoios_viga_em_viga(self, modelo: ModeloPortico) -> None:
        """
        Percorre os Vãos do modelo já montado em busca de cruzamentos
        Viga x Viga sem Apoio declarado, e levanta ApoioNaoDefinidoError
        caso encontre algum.

        PENDÊNCIA: a forma exata de identificar "isto é um cruzamento
        Viga x Viga sem Apoio" depende de como ModeloPortico.montar()
        vier a marcar nós compartilhados entre duas Vigas -- a definir
        junto com o algoritmo de interseção.
        """
        raise NotImplementedError
