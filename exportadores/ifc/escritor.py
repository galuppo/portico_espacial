"""
IfcWriter (interface de baixo nível) + EscritorIfcManual (implementação por
escrita manual de STEP, sem depender de ifcopenshell).

Responsabilidade deste módulo: SÓ criar/referenciar/serializar entidades IFC
e gravar o arquivo. NÃO conhece nada do domínio do Pórtico Espacial (Pilar,
Viga, Laje...) -- quem decide quais entidades existem e com que atributos é
o ExportadorIfc (módulo separado), que chama EscritorIfcManual.criar_entidade()
pra cada uma.

Mecânica validada por execução real (arquivo de teste aberto, navegado
semanticamente e com geometria tesselada com sucesso via ifcopenshell)
durante o desenho da arquitetura -- ver notas do projeto.
"""

import re
import uuid
from abc import ABC, abstractmethod
from base64 import b64encode
from dataclasses import dataclass
from typing import Any, Dict, List

from .ordem_atributos import ORDEM_ATRIBUTOS, ENTIDADES_COM_ATRIBUTO_DERIVADO_INICIAL


# ======================================================================
# GUID -- algoritmo confirmado contra o código-fonte oficial do
# ifcopenshell/guid.py (LGPL, Thomas Krijnen), que por sua vez segue a
# orientação de implementação da buildingSMART. Usa só `uuid` e `base64`
# da biblioteca padrão -- não depende do ifcopenshell de fato.
# ======================================================================

_ALFABETO_BASE64_PADRAO = (
	"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
)
_ALFABETO_BASE64_IFC = (
	"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
)
_TRADUCAO_PADRAO_PARA_IFC = str.maketrans(_ALFABETO_BASE64_PADRAO, _ALFABETO_BASE64_IFC)


def comprimir_guid(uuid_hex: str) -> str:
	"""
	Converte um UUID (string hex, com ou sem hífens) pro formato comprimido
	de 22 caracteres do IfcGloballyUniqueId.

	Algoritmo (idêntico ao ifcopenshell.guid.compress):
	  1. remove separadores do hex
	  2. prefixa com "0000" (2 bytes zerados) -> 18 bytes ao todo
	  3. base64 padrão desses 18 bytes -> 24 caracteres, sem padding "="
	  4. descarta os 2 primeiros caracteres (originados do prefixo do
	     passo 2) -> 22 caracteres
	  5. traduz do alfabeto base64 padrão pro alfabeto do IFC
	"""
	hex_limpo = re.sub(r"\W", "", uuid_hex.lower())
	hex_com_padding = "0000" + hex_limpo
	bruto = bytes.fromhex(hex_com_padding)
	base64_padrao = b64encode(bruto).decode()[2:]
	return base64_padrao.translate(_TRADUCAO_PADRAO_PARA_IFC)


def guid_deterministico(namespace: uuid.UUID, chave: str) -> str:
	"""
	GUID IFC determinístico: a mesma `chave` sempre produz o mesmo GUID
	(mesmo em reexportações). `chave` normalmente é o id do GeradorId do
	elemento de domínio, como string.
	"""
	u = uuid.uuid5(namespace, chave)
	return comprimir_guid(u.hex)


# ======================================================================
# Marcador de valor enumerado IFC (ex.: .LENGTHUNIT., .COLUMN.) --
# distingue de uma string comum, que é serializada entre aspas.
# ======================================================================
@dataclass(frozen=True)
class ValorEnum:
	valor: str


# ======================================================================
# Referência opaca a uma entidade IFC já criada. O ExportadorIfc nunca olha
# pra dentro disso -- só guarda e repassa como atributo de outra entidade.
# ======================================================================
class RefEntidadeIfc:
	pass


@dataclass(frozen=True)
class _RefEntidadeIfcManual(RefEntidadeIfc):
	"""Pro EscritorIfcManual, a referência é só o número #id do STEP."""
	id_step: int


# ======================================================================
# Interface do Writer
# ======================================================================
class IfcWriter(ABC):

	@abstractmethod
	def criar_entidade(self, tipo: str, **atributos: Any) -> RefEntidadeIfc:
		"""
		Cria uma entidade IFC do tipo informado (ex.: "IFCCOLUMN") com os
		atributos dados (chaves = nomes dos atributos no schema EXPRESS).
		Cada atributo pode ser um valor simples, None (atributo omitido),
		um ValorEnum, ou outra RefEntidadeIfc (referência a entidade já
		criada). Retorna uma referência opaca, reutilizável em chamadas
		futuras de criar_entidade().
		"""
		raise NotImplementedError

	@abstractmethod
	def salvar(self, caminho: str) -> None:
		"""Serializa e grava o arquivo IFC completo no caminho informado."""
		raise NotImplementedError


# ======================================================================
# Implementação: escreve STEP (.ifc) manualmente, sem ifcopenshell.
# ======================================================================
class EscritorIfcManual(IfcWriter):

	def __init__(self, schema: str = "IFC4"):
		self._schema = schema
		self._proximo_id = 1
		self._linhas: List[str] = []  # linhas já serializadas da seção DATA

	def criar_entidade(self, tipo: str, **atributos: Any) -> RefEntidadeIfc:
		ordem = ORDEM_ATRIBUTOS.get(tipo)
		if ordem is None:
			raise ValueError(
				f"Ordem de atributos não definida pra '{tipo}' em ORDEM_ATRIBUTOS."
			)

		# atributos passados que não existem na ordem esperada indicam
		# erro de quem chamou (nome errado, typo) -- falha cedo em vez de
		# ignorar silenciosamente
		desconhecidos = set(atributos) - set(ordem)
		if desconhecidos:
			raise ValueError(
				f"Atributo(s) desconhecido(s) pra '{tipo}': {sorted(desconhecidos)}. "
				f"Esperado(s): {ordem}"
			)

		partes = [self._serializar_valor(atributos.get(nome)) for nome in ordem]

		if tipo in ENTIDADES_COM_ATRIBUTO_DERIVADO_INICIAL:
			partes.insert(0, "*")

		id_atual = self._proximo_id
		self._proximo_id += 1
		self._linhas.append(f"#{id_atual}={tipo}({','.join(partes)});")
		return _RefEntidadeIfcManual(id_atual)

	def _serializar_valor(self, valor: Any) -> str:
		if valor is None:
			return "$"
		if isinstance(valor, _RefEntidadeIfcManual):
			return f"#{valor.id_step}"
		if isinstance(valor, ValorEnum):
			return f".{valor.valor}."
		if isinstance(valor, str):
			escapada = valor.replace("'", "''")
			return f"'{escapada}'"
		if isinstance(valor, bool):
			return ".T." if valor else ".F."
		if isinstance(valor, (list, tuple)):
			return "(" + ",".join(self._serializar_valor(v) for v in valor) + ")"
		if isinstance(valor, (int, float)):
			return repr(valor)
		raise TypeError(f"Tipo não serializável pro STEP: {type(valor)!r} (valor={valor!r})")

	def salvar(self, caminho: str) -> None:
		cabecalho = (
			"ISO-10303-21;\n"
			"HEADER;\n"
			"FILE_DESCRIPTION((''),'2;1');\n"
			"FILE_NAME('','',(''),(''),'','','');\n"
			f"FILE_SCHEMA(('{self._schema}'));\n"
			"ENDSEC;\n"
			"DATA;\n"
		)
		rodape = "ENDSEC;\nEND-ISO-10303-21;\n"
		with open(caminho, "w", encoding="utf-8") as f:
			f.write(cabecalho)
			for linha in self._linhas:
				f.write(linha + "\n")
			f.write(rodape)
