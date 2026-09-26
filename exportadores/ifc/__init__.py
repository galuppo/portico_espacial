"""
Subpacote do exportador IFC do Pórtico Espacial.

Uso:

    from .exportadores.ifc import ExportadorIfc, EscritorIfcManual

    modelo.montar()
    ExportadorIfc(modelo, EscritorIfcManual()).exportar("saida.ifc")

Organização interna:
  - ordem_atributos.py -- tabela de ordem posicional de atributos por
    entidade IFC (dado puro, sem lógica)
  - escritor.py         -- IfcWriter (interface) + EscritorIfcManual
    (escrita manual de STEP) + utilitário de GUID determinístico
  - exportador.py        -- ExportadorIfc: conhece o domínio do Pórtico
    Espacial e o schema IFC, percorre o ModeloPortico e chama o Writer
"""

from .escritor import EscritorIfcManual, IfcWriter, RefEntidadeIfc, ValorEnum, guid_deterministico
from .exportador import NAMESPACE_PORTICO_ESPACIAL, ExportadorIfc

__all__ = [
	"ExportadorIfc",
	"EscritorIfcManual",
	"IfcWriter",
	"RefEntidadeIfc",
	"ValorEnum",
	"guid_deterministico",
	"NAMESPACE_PORTICO_ESPACIAL",
]
