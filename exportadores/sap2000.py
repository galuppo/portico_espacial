"""
Adaptador de exportação: traduz um ModeloPortico (já montado) para o
SAP2000, via a OAPI (reaproveitando o pacote `sap2000_oapi` do projeto
sap2000-automation).

Esta é a ÚNICA parte do Pórtico Espacial que conhece o SAP2000 -- o
modelo de domínio (Pilar, Viga, Laje, Barra) não importa nada deste
módulo, garantindo que o modelo continue independente e reutilizável
com outros alvos de exportação no futuro.
"""

from __future__ import annotations

from ..estrutura import ModeloPortico


class ExportadorSap2000:
    """Exporta um ModeloPortico montado para uma instância do SAP2000 aberta via OAPI."""

    def exportar(self, modelo: ModeloPortico) -> None:
        """
        Para cada Barra do modelo (Lances, Vãos, Links, barras de grid),
        cria o frame correspondente no SAP2000, usando o id da Barra
        como label.
        """
        raise NotImplementedError
