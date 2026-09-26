"""
exportadores/ifc.py

ExportadorIfc: conhece o domínio do Pórtico Espacial e o schema IFC4;
percorre um ModeloPortico já montado e usa um IfcWriter (ver escritor.py)
pra criar as entidades correspondentes -- este módulo NUNCA fala STEP
diretamente, só chama writer.criar_entidade(tipo, **atributos).

ESCOPO DESTA VERSÃO:
  - estrutura espacial (Pavimento -> IfcBuildingStorey) e unidades
  - camada analítica completa (IfcStructuralCurveMember + IfcStructuralPointConnection,
    condição de contorno a partir de Restricao) pra Pilar, Viga, Link e Laje (grelha)
  - camada física completa, COM geometria de sólido (IfcExtrudedAreaSolid), pra
    Pilar/Viga/Laje -- ligada à camada analítica (IfcRelAssignsToProduct), ao
    Pavimento (IfcRelContainedInSpatialStructure) e ao IfcMaterial
  - material (IfcMaterial), deduplicado por Material.nome

CONVENÇÃO DE ORIENTAÇÃO 3D (Pilar/Viga), confirmada com o usuário -- mesma
convenção já usada em ExportadorDxf.exportar_solido() (padrão SAP2000):
  eixo1 = ao longo da barra (do primeiro no_inicial do grupo ao último no_final)
  eixo2 = "pra cima" -- projeção de Z global no plano perpendicular a eixo1
          (ou de X global, se a barra for quase vertical) + rotação da Barra
  eixo3 = eixo1 × eixo2
  altura da seção (eixo forte) alinhada a eixo2; largura a eixo3
  Pilar: seção centrada no eixo (eixo2 ∈ [-altura/2, +altura/2])
  Viga: referência é o TOPO da seção (ver docstring de interseccao.py) --
        seção desce a partir da referência (eixo2 ∈ [-altura, 0])

CONVENÇÃO DA LAJE, confirmada com o usuário: o contorno (laje.grelha.poligono)
representa o TOPO da laje; o sólido extrude PRA BAIXO por laje.secao.altura
(espessura). Só suporta laje horizontal nesta versão (não verifica plano
inclinado) -- Grelha em si suporta planos inclinados, mas a extrusão do
sólido físico aqui assume Z constante no contorno.

PENDÊNCIAS:
  - Laje inclinada (plano não-horizontal) na geometria de sólido física
  - Perfis não-retangulares (SecaoTransversal só tem SecaoRetangular hoje)
"""

from __future__ import annotations

import math
import uuid
from typing import Dict, List, Optional, Tuple

from ...elementos import Apoio, ApoioRestricao, Barra, Lance, Pavimento, Pilar, Vao, Viga
from ...estrutura import ModeloPortico
from ...geometria import Ponto
from ...materiais import Material
from ...secoes import SecaoRetangular
from ...vinculos import GrauLiberdade, Restricao, TipoRestricao

from .escritor import IfcWriter, RefEntidadeIfc, ValorEnum, guid_deterministico


# Namespace fixo do projeto pra geração determinística de GUID (ver
# ifc_writer.guid_deterministico). NÃO mudar depois de haver arquivos
# exportados em uso -- mudar isso faz toda reexportação gerar GUIDs novos,
# quebrando o vínculo com versões já entregues.
NAMESPACE_PORTICO_ESPACIAL = uuid.UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")


class ExportadorIfc:

	def __init__(self, modelo: ModeloPortico, writer: IfcWriter, unidade_comprimento: str = "m"):
		if unidade_comprimento != "m":
			# conversor de unidades do projeto ainda não existe (pendência
			# maior, registrada à parte) -- por ora só aceita metros, que é
			# a unidade que o modelo já usa hoje
			raise NotImplementedError(
				"Só unidade_comprimento='m' é suportada nesta versão."
			)
		self._modelo = modelo
		self._w = writer

		# caches -- chaveados por VALOR, não identidade (Ponto é frozen
		# dataclass, __eq__/__hash__ por valor; confirmado que
		# ModeloPortico.montar() conta com igualdade por valor, não reaproveita
		# necessariamente o mesmo objeto Ponto entre elementos conectados)
		self._storeys: Dict[str, RefEntidadeIfc] = {}
		self._nos_analiticos: Dict[Ponto, RefEntidadeIfc] = {}
		self._materiais_ifc: Dict[str, RefEntidadeIfc] = {}

		self._eixo_padrao: Optional[RefEntidadeIfc] = None
		self._edificio: Optional[RefEntidadeIfc] = None
		self._contexto: Optional[RefEntidadeIfc] = None

	# ------------------------------------------------------------------
	# ponto de entrada
	# ------------------------------------------------------------------

	def exportar(self, caminho: str) -> None:
		unidades = self._escrever_unidades()
		self._escrever_projeto(unidades)

		for pavimento in self._modelo.pavimentos:
			self._escrever_storey(pavimento)

		for pilar in self._modelo.pilares:
			self._escrever_pilar(pilar)
		for viga in self._modelo.vigas:
			self._escrever_viga(viga)
		for link in self._modelo.links:
			self._escrever_link(link)
		for laje in self._modelo.lajes:
			self._escrever_laje(laje)

		self._w.salvar(caminho)

	# ------------------------------------------------------------------
	# estrutura espacial e unidades
	# ------------------------------------------------------------------

	def _eixo_origem(self) -> RefEntidadeIfc:
		"""IfcAxis2Placement3D na origem global (0,0,0) -- reaproveitado sempre que
		um placement não precisa de orientação própria."""
		if self._eixo_padrao is None:
			origem = self._w.criar_entidade("IFCCARTESIANPOINT", Coordinates=[0.0, 0.0, 0.0])
			self._eixo_padrao = self._w.criar_entidade(
				"IFCAXIS2PLACEMENT3D", Location=origem, Axis=None, RefDirection=None
			)
		return self._eixo_padrao

	def _contexto_geometrico(self) -> RefEntidadeIfc:
		"""IfcGeometricRepresentationContext -- 1 só pro arquivo inteiro,
		referenciado por todo IfcShapeRepresentation."""
		if self._contexto is None:
			self._contexto = self._w.criar_entidade(
				"IFCGEOMETRICREPRESENTATIONCONTEXT",
				ContextIdentifier=None, ContextType="Model", CoordinateSpaceDimension=3,
				Precision=1e-5, WorldCoordinateSystem=self._eixo_origem(), TrueNorth=None,
			)
		return self._contexto

	def _escrever_unidades(self) -> RefEntidadeIfc:
		unidade_comprimento = self._w.criar_entidade(
			"IFCSIUNIT", UnitType=ValorEnum("LENGTHUNIT"), Prefix=None, Name=ValorEnum("METRE")
		)
		return self._w.criar_entidade("IFCUNITASSIGNMENT", Units=[unidade_comprimento])

	def _escrever_projeto(self, unidades: RefEntidadeIfc) -> RefEntidadeIfc:
		projeto = self._w.criar_entidade(
			"IFCPROJECT",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, "projeto"),
			OwnerHistory=None, Name="Portico Espacial", Description=None,
			ObjectType=None, LongName=None, Phase=None,
			RepresentationContexts=[self._contexto_geometrico()], UnitsInContext=unidades,
		)
		placement_site = self._w.criar_entidade(
			"IFCLOCALPLACEMENT", PlacementRelTo=None, RelativePlacement=self._eixo_origem()
		)
		site = self._w.criar_entidade(
			"IFCSITE",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, "site"),
			OwnerHistory=None, Name="Terreno", Description=None,
			ObjectType=None, ObjectPlacement=placement_site, Representation=None,
			LongName=None, CompositionType=ValorEnum("ELEMENT"),
			RefLatitude=None, RefLongitude=None, RefElevation=None,
			LandTitleNumber=None, SiteAddress=None,
		)
		placement_edificio = self._w.criar_entidade(
			"IFCLOCALPLACEMENT", PlacementRelTo=placement_site, RelativePlacement=self._eixo_origem()
		)
		edificio = self._w.criar_entidade(
			"IFCBUILDING",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, "edificio"),
			OwnerHistory=None, Name="Edificio", Description=None,
			ObjectType=None, ObjectPlacement=placement_edificio, Representation=None,
			LongName=None, CompositionType=ValorEnum("ELEMENT"),
			ElevationOfRefHeight=None, ElevationOfTerrain=None, BuildingAddress=None,
		)
		self._w.criar_entidade(
			"IFCRELAGGREGATES",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, "agrega:projeto:site"),
			OwnerHistory=None, Name=None, Description=None,
			RelatingObject=projeto, RelatedObjects=[site],
		)
		self._w.criar_entidade(
			"IFCRELAGGREGATES",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, "agrega:site:edificio"),
			OwnerHistory=None, Name=None, Description=None,
			RelatingObject=site, RelatedObjects=[edificio],
		)
		self._edificio = edificio
		return projeto

	def _escrever_storey(self, pavimento: Pavimento) -> RefEntidadeIfc:
		ponto = self._w.criar_entidade("IFCCARTESIANPOINT", Coordinates=[0.0, 0.0, float(pavimento.elevacao)])
		eixo = self._w.criar_entidade("IFCAXIS2PLACEMENT3D", Location=ponto, Axis=None, RefDirection=None)
		placement = self._w.criar_entidade("IFCLOCALPLACEMENT", PlacementRelTo=None, RelativePlacement=eixo)
		storey = self._w.criar_entidade(
			"IFCBUILDINGSTOREY",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"storey:{pavimento.nome}"),
			OwnerHistory=None, Name=pavimento.nome, Description=None,
			ObjectType=None, ObjectPlacement=placement, Representation=None,
			LongName=None, CompositionType=ValorEnum("ELEMENT"), Elevation=float(pavimento.elevacao),
		)
		self._w.criar_entidade(
			"IFCRELAGGREGATES",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"agrega:edificio:{pavimento.nome}"),
			OwnerHistory=None, Name=None, Description=None,
			RelatingObject=self._edificio, RelatedObjects=[storey],
		)
		self._storeys[pavimento.nome] = storey
		return storey

	def _storey_de(self, pavimento: Pavimento) -> RefEntidadeIfc:
		return self._storeys[pavimento.nome]

	# ------------------------------------------------------------------
	# nó analítico + condição de contorno (compartilhado por Pilar/Viga)
	# ------------------------------------------------------------------

	def _no_analitico(self, ponto: Ponto, apoio: Optional[Apoio]) -> RefEntidadeIfc:
		"""
		IfcStructuralPointConnection num Ponto do domínio, cacheado por
		VALOR do Ponto -- dois nós com mesmo (x,y,z) são o mesmo nó
		estrutural, mesmo sendo objetos Python diferentes.

		`apoio` só é considerado na primeira vez que o nó é criado (faz
		sentido, já que o nó físico só tem uma condição de contorno).
		Regra já fechada: Apoio em si NUNCA gera entidade (nem
		ApoioElemento, nem o próprio wrapper ApoioRestricao) -- só a
		Restricao de fato (dentro de um ApoioRestricao) vira
		IfcBoundaryNodeCondition.
		"""
		existente = self._nos_analiticos.get(ponto)
		if existente is not None:
			return existente

		condicao = None
		if isinstance(apoio, ApoioRestricao):
			condicao = self._escrever_condicao_contorno(apoio.restricao)

		ponto_ifc = self._w.criar_entidade("IFCCARTESIANPOINT", Coordinates=[float(ponto.x), float(ponto.y), float(ponto.z)])
		eixo = self._w.criar_entidade("IFCAXIS2PLACEMENT3D", Location=ponto_ifc, Axis=None, RefDirection=None)
		placement = self._w.criar_entidade("IFCLOCALPLACEMENT", PlacementRelTo=None, RelativePlacement=eixo)

		no = self._w.criar_entidade(
			"IFCSTRUCTURALPOINTCONNECTION",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"no:{ponto.x}:{ponto.y}:{ponto.z}"),
			OwnerHistory=None, Name=None, Description=None, ObjectType=None,
			ObjectPlacement=placement, Representation=None,
			AppliedCondition=condicao, ConditionCoordinateSystem=None,
		)
		self._nos_analiticos[ponto] = no
		return no

	def _valor_grau_liberdade(self, grau: GrauLiberdade):
		"""
		Traduz um GrauLiberdade pro valor esperado por
		IfcBoundaryNodeCondition (select IfcBoolean | IfcLinearStiffnessMeasure):
		  LIVRE       -> None (atributo omitido: sem restrição registrada)
		  RESTRINGIDO -> True (travado)
		  ELASTICO    -> valor numérico de rigidez
		"""
		if grau.tipo == TipoRestricao.LIVRE:
			return None
		if grau.tipo == TipoRestricao.RESTRINGIDO:
			return True
		return grau.rigidez

	def _escrever_condicao_contorno(self, restricao: Restricao) -> RefEntidadeIfc:
		return self._w.criar_entidade(
			"IFCBOUNDARYNODECONDITION",
			Name=None,
			TranslationalStiffnessX=self._valor_grau_liberdade(restricao.translacao_x),
			TranslationalStiffnessY=self._valor_grau_liberdade(restricao.translacao_y),
			TranslationalStiffnessZ=self._valor_grau_liberdade(restricao.translacao_z),
			RotationalStiffnessX=self._valor_grau_liberdade(restricao.rotacao_x),
			RotationalStiffnessY=self._valor_grau_liberdade(restricao.rotacao_y),
			RotationalStiffnessZ=self._valor_grau_liberdade(restricao.rotacao_z),
		)

	# ------------------------------------------------------------------
	# material
	# ------------------------------------------------------------------

	def _material_ifc(self, material: Material) -> RefEntidadeIfc:
		"""
		Cacheado por Material.nome -- Material não é frozen (não dá pra
		usar como chave de dict diretamente), e nome é o identificador que
		o usuário escolhe pra cada material distinto (ex.: "C30").
		"""
		existente = self._materiais_ifc.get(material.nome)
		if existente is not None:
			return existente
		entidade = self._w.criar_entidade("IFCMATERIAL", Name=material.nome, Description=None, Category=None)
		self._materiais_ifc[material.nome] = entidade
		return entidade

	# ------------------------------------------------------------------
	# agrupamento físico (regra combinada: quebra em qualquer mudança de
	# seção, material ou rotação -- vale igual pra Pilar e Viga)
	# ------------------------------------------------------------------

	def _agrupar_indices_por_secao_material_rotacao(self, barras: List[Barra]) -> List[List[int]]:
		"""
		Agrupa os ÍNDICES de uma sequência ordenada de Barras em sub-listas
		contíguas de mesma seção, material (por .nome) e rotação. Devolve
		índices (não os objetos) pra não depender de comparação/identidade
		de Lance/Vao, que carregam referência circular ao pai.
		"""
		grupos: List[List[int]] = []
		grupo_atual: List[int] = []
		chave_atual = None
		for indice, barra in enumerate(barras):
			chave = (barra.secao, barra.material.nome, barra.rotacao)
			if grupo_atual and chave != chave_atual:
				grupos.append(grupo_atual)
				grupo_atual = []
			grupo_atual.append(indice)
			chave_atual = chave
		if grupo_atual:
			grupos.append(grupo_atual)
		return grupos

	# ------------------------------------------------------------------
	# geometria 3D (orientação da barra + perfil retangular) -- convenção
	# SAP2000, confirmada com o usuário (ver docstring do módulo)
	# ------------------------------------------------------------------

	def _eixos_locais(
		self, p_ini: Ponto, p_fim: Ponto, rotacao_graus: float
	) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float], float]:
		"""
		Calcula (eixo1, eixo2, eixo3, comprimento) pra uma barra de p_ini a
		p_fim, com a rotação própria aplicada. eixo1 = direção da barra;
		eixo2 = "pra cima" (Z global projetado, ou X global se a barra for
		quase vertical) rotacionado por `rotacao_graus` em torno de eixo1;
		eixo3 = eixo1 × eixo2.
		"""
		dx, dy, dz = p_fim.x - p_ini.x, p_fim.y - p_ini.y, p_fim.z - p_ini.z
		comprimento = math.sqrt(dx * dx + dy * dy + dz * dz)
		if comprimento < 1e-9:
			raise ValueError("Barra de comprimento nulo -- não dá pra orientar geometricamente.")
		e1 = (dx / comprimento, dy / comprimento, dz / comprimento)

		quase_vertical = abs(e1[2]) > 1 - 1e-9  # mesma tolerância do ExportadorDxf._eixos_locais
		ref = (1.0, 0.0, 0.0) if quase_vertical else (0.0, 0.0, 1.0)

		produto_escalar = ref[0] * e1[0] + ref[1] * e1[1] + ref[2] * e1[2]
		bruto = tuple(ref[i] - produto_escalar * e1[i] for i in range(3))
		norma = math.sqrt(sum(c * c for c in bruto))
		e2_0 = tuple(c / norma for c in bruto)

		e3_0 = (
			e1[1] * e2_0[2] - e1[2] * e2_0[1],
			e1[2] * e2_0[0] - e1[0] * e2_0[2],
			e1[0] * e2_0[1] - e1[1] * e2_0[0],
		)

		rad = math.radians(rotacao_graus)
		cos_r, sin_r = math.cos(rad), math.sin(rad)
		e2 = tuple(e2_0[i] * cos_r + e3_0[i] * sin_r for i in range(3))
		e3 = tuple(-e2_0[i] * sin_r + e3_0[i] * cos_r for i in range(3))

		return e1, e2, e3, comprimento

	def _vertices_anti_horario(self, vertices: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
		"""Garante sentido anti-horário (área com sinal positiva) -- mesmo critério do ExportadorDxf,
		pra normal do perfil sair consistente independente da ordem em que os vértices foram informados."""
		area_dupla = sum(
			vertices[i][0] * vertices[(i + 1) % len(vertices)][1] - vertices[(i + 1) % len(vertices)][0] * vertices[i][1]
			for i in range(len(vertices))
		)
		return vertices if area_dupla > 0 else list(reversed(vertices))

	def _perfil_pontos(self, secao, referencia_topo: bool) -> List[RefEntidadeIfc]:
		"""
		Pontos (2D locais) do contorno do perfil, na ordem do laço fechado
		-- usa `secao.vertices` genericamente (funciona com qualquer
		SecaoTransversal: SecaoRetangular, SecaoPoligonal, etc.), sem
		depender de uma implementação específica.

		`secao.vertices` vem como (largura, altura) -- mesma convenção que
		`ExportadorDxf` usa (vx=largura→eixo3, vy=altura→eixo2). Já o
		ObjectPlacement daqui usa local-X=eixo2 (altura) e local-Y=eixo3
		(largura) -- ordem invertida -- então as componentes são trocadas
		na conversão pra não sair uma seção rotacionada 90° (largura no
		lugar de altura) pra qualquer perfil não-quadrado.

		`referencia_topo=True` (Viga): `no_inicial`/`no_final` representam
		o TOPO da seção, não o eixo -- desloca o perfil (na componente que
		representa a altura, já em local-X depois da troca) até seu ponto
		mais alto coincidir com a referência, em vez de ficar centrado
		nela. Generaliza pra qualquer perfil (não só retangular): desloca
		pelo valor máximo real dos vértices, não por altura/2 fixo.
		`referencia_topo=False` (Pilar): perfil fica como veio de
		`secao.vertices` (já centrado na origem, por convenção de
		SecaoTransversal), sem deslocamento.
		"""
		vertices_largura_altura = list(secao.vertices)
		vertices = [(altura, largura) for largura, altura in vertices_largura_altura]  # -> (X=altura, Y=largura)
		vertices = self._vertices_anti_horario(vertices)
		if referencia_topo:
			x_maximo = max(vx for vx, _vy in vertices)  # X agora é a componente de altura
			vertices = [(vx - x_maximo, vy) for vx, vy in vertices]
		return [self._w.criar_entidade("IFCCARTESIANPOINT", Coordinates=[float(v[0]), float(v[1])]) for v in vertices]

	# ------------------------------------------------------------------
	# elemento físico (compartilhado por Pilar/Viga)
	# ------------------------------------------------------------------

	def _escrever_elemento_fisico(
		self, tipo_ifc: str, nome: str, barras_grupo: List[Barra],
		membros_analiticos: List[RefEntidadeIfc], pavimento: Pavimento, tipo_predefinido: str,
		chave_guid: str,
	) -> RefEntidadeIfc:
		"""
		Cria o elemento físico com geometria de sólido real
		(IfcExtrudedAreaSolid, seção real extrudada ao longo da barra),
		ligado aos membros analíticos correspondentes
		(IfcRelAssignsToProduct), ao Pavimento (IfcRelContainedInSpatialStructure)
		e ao Material (IfcRelAssociatesMaterial).

		Funciona com qualquer SecaoTransversal (usa `secao.vertices`
		genericamente) -- não fica mais restrito a SecaoRetangular.
		"""
		secao = barras_grupo[0].secao

		p_ini = barras_grupo[0].no_inicial
		p_fim = barras_grupo[-1].no_final
		e1, e2, e3, comprimento = self._eixos_locais(p_ini, p_fim, barras_grupo[0].rotacao)

		origem_ifc = self._w.criar_entidade("IFCCARTESIANPOINT", Coordinates=[float(p_ini.x), float(p_ini.y), float(p_ini.z)])
		eixo1_ifc = self._w.criar_entidade("IFCDIRECTION", DirectionRatios=[float(c) for c in e1])
		eixo2_ifc = self._w.criar_entidade("IFCDIRECTION", DirectionRatios=[float(c) for c in e2])
		orientacao = self._w.criar_entidade(
			"IFCAXIS2PLACEMENT3D", Location=origem_ifc, Axis=eixo1_ifc, RefDirection=eixo2_ifc
		)
		placement = self._w.criar_entidade("IFCLOCALPLACEMENT", PlacementRelTo=None, RelativePlacement=orientacao)

		# perfil no plano local (eixo2=altura/eixo forte, eixo3=largura) --
		# referência é o topo da seção só pra Viga (ver docstring do módulo)
		pontos_perfil = self._perfil_pontos(secao, referencia_topo=(tipo_ifc == "IFCBEAM"))
		contorno = self._w.criar_entidade("IFCPOLYLINE", Points=pontos_perfil + [pontos_perfil[0]])
		perfil = self._w.criar_entidade(
			"IFCARBITRARYCLOSEDPROFILEDEF", ProfileType=ValorEnum("AREA"), ProfileName=None, OuterCurve=contorno
		)
		# extrusão no sistema local de IDENTIDADE (a orientação real já foi
		# aplicada inteira no ObjectPlacement acima) -- extrude ao longo do
		# próprio eixo Z local, que dentro do placement já corresponde a eixo1
		direcao_extrusao = self._w.criar_entidade("IFCDIRECTION", DirectionRatios=[0.0, 0.0, 1.0])
		solido = self._w.criar_entidade(
			"IFCEXTRUDEDAREASOLID", SweptArea=perfil, Position=self._eixo_origem(),
			ExtrudedDirection=direcao_extrusao, Depth=comprimento,
		)
		representacao = self._w.criar_entidade(
			"IFCSHAPEREPRESENTATION", ContextOfItems=self._contexto_geometrico(),
			RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[solido],
		)
		forma = self._w.criar_entidade(
			"IFCPRODUCTDEFINITIONSHAPE", Name=None, Description=None, Representations=[representacao]
		)

		elemento = self._w.criar_entidade(
			tipo_ifc,
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, chave_guid),
			OwnerHistory=None, Name=nome, Description=None, ObjectType=None,
			ObjectPlacement=placement, Representation=forma,
			Tag=None, PredefinedType=ValorEnum(tipo_predefinido),
		)

		self._w.criar_entidade(
			"IFCRELASSIGNSTOPRODUCT",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"assign:{chave_guid}"),
			OwnerHistory=None, Name=None, Description=None,
			RelatedObjects=membros_analiticos, RelatedObjectsType=None, RelatingProduct=elemento,
		)
		self._w.criar_entidade(
			"IFCRELCONTAINEDINSPATIALSTRUCTURE",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"contido:{chave_guid}"),
			OwnerHistory=None, Name=None, Description=None,
			RelatedElements=[elemento], RelatingStructure=self._storey_de(pavimento),
		)
		material_ifc = self._material_ifc(barras_grupo[0].material)
		self._w.criar_entidade(
			"IFCRELASSOCIATESMATERIAL",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"material:{chave_guid}"),
			OwnerHistory=None, Name=None, Description=None,
			RelatedObjects=[elemento], RelatingMaterial=material_ifc,
		)
		return elemento

	# ------------------------------------------------------------------
	# pilar
	# ------------------------------------------------------------------

	def _escrever_pilar(self, pilar: Pilar) -> None:
		lances = sorted(pilar.lances, key=lambda l: l.indice)

		# nós analíticos: o da base carrega Pilar.apoio_base, o do topo
		# carrega Pilar.apoio_topo; quebras intermediárias (entre Lances)
		# não têm Apoio nenhum (Pilar não guarda apoio em quebra
		# intermediária, ver docstring de Lance em elementos.py)
		nos: List[RefEntidadeIfc] = [self._no_analitico(lances[0].no_inicial, pilar.apoio_base)]
		for indice, lance in enumerate(lances):
			apoio = pilar.apoio_topo if indice == len(lances) - 1 else None
			nos.append(self._no_analitico(lance.no_final, apoio))

		barras_analiticas: List[RefEntidadeIfc] = []
		for indice, lance in enumerate(lances):
			barra_ifc = self._w.criar_entidade(
				"IFCSTRUCTURALCURVEMEMBER",
				GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"barra:{lance.id}"),
				OwnerHistory=None, Name=lance.nome, Description=None, ObjectType=None,
				ObjectPlacement=None, Representation=None,
				PredefinedType=ValorEnum("RIGID_JOINED_MEMBER"), Axis=None,
			)
			barras_analiticas.append(barra_ifc)
			for extremidade, no in (("ini", nos[indice]), ("fim", nos[indice + 1])):
				self._w.criar_entidade(
					"IFCRELCONNECTSSTRUCTURALMEMBER",
					GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"conecta:{lance.id}:{extremidade}"),
					OwnerHistory=None, Name=None, Description=None,
					RelatingStructuralMember=barra_ifc, RelatedStructuralConnection=no,
					AppliedCondition=None, AdditionalConditions=None, SupportedLength=None,
					ConditionCoordinateSystem=None,
				)

		for grupo_indices in self._agrupar_indices_por_secao_material_rotacao(lances):
			grupo_lances = [lances[i] for i in grupo_indices]
			grupo_analiticos = [barras_analiticas[i] for i in grupo_indices]
			self._escrever_elemento_fisico(
				tipo_ifc="IFCCOLUMN", nome=pilar.nome, barras_grupo=grupo_lances,
				membros_analiticos=grupo_analiticos,
				pavimento=grupo_lances[0].pavimento, tipo_predefinido="COLUMN",
				chave_guid=f"fisico:pilar:{grupo_lances[0].id}",
			)

	# ------------------------------------------------------------------
	# viga
	# ------------------------------------------------------------------

	def _pavimento_mais_proximo(self, viga: Viga, z_referencia: float) -> Pavimento:
		"""
		Escolhe, dentre viga.pavimentos, o mais próximo em elevação de
		z_referencia. Critério PRÓPRIO deste exportador -- não reaproveita
		nenhuma lógica do exportador DXF (não tenho acesso ao código-fonte
		dele pra confirmar o critério exato que ele usa); serve só pra
		decidir em qual IfcBuildingStorey o elemento físico da Viga fica
		contido.
		"""
		if not viga.pavimentos:
			raise ValueError(
				f"Viga '{viga.nome}' não tem nenhum Pavimento em viga.pavimentos -- "
				"não dá pra decidir o IfcBuildingStorey de contenção."
			)
		return min(viga.pavimentos, key=lambda p: abs(p.elevacao - z_referencia))

	def _escrever_viga(self, viga: Viga) -> None:
		vaos = sorted(viga.vaos, key=lambda v: v.indice)

		barras_analiticas: List[RefEntidadeIfc] = []
		for vao in vaos:
			no_ini = self._no_analitico(vao.no_inicial, vao.apoio_inicial)
			no_fim = self._no_analitico(vao.no_final, vao.apoio_final)

			barra_ifc = self._w.criar_entidade(
				"IFCSTRUCTURALCURVEMEMBER",
				GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"barra:{vao.id}"),
				OwnerHistory=None, Name=vao.nome, Description=None, ObjectType=None,
				ObjectPlacement=None, Representation=None,
				PredefinedType=ValorEnum("RIGID_JOINED_MEMBER"), Axis=None,
			)
			barras_analiticas.append(barra_ifc)
			for extremidade, no in (("ini", no_ini), ("fim", no_fim)):
				self._w.criar_entidade(
					"IFCRELCONNECTSSTRUCTURALMEMBER",
					GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"conecta:{vao.id}:{extremidade}"),
					OwnerHistory=None, Name=None, Description=None,
					RelatingStructuralMember=barra_ifc, RelatedStructuralConnection=no,
					AppliedCondition=None, AdditionalConditions=None, SupportedLength=None,
					ConditionCoordinateSystem=None,
				)

		for grupo_indices in self._agrupar_indices_por_secao_material_rotacao(vaos):
			grupo_vaos = [vaos[i] for i in grupo_indices]
			grupo_analiticos = [barras_analiticas[i] for i in grupo_indices]
			z_medio = sum((v.no_inicial.z + v.no_final.z) / 2 for v in grupo_vaos) / len(grupo_vaos)
			pavimento = self._pavimento_mais_proximo(viga, z_medio)
			self._escrever_elemento_fisico(
				tipo_ifc="IFCBEAM", nome=viga.nome, barras_grupo=grupo_vaos,
				membros_analiticos=grupo_analiticos,
				pavimento=pavimento, tipo_predefinido="BEAM",
				chave_guid=f"fisico:viga:{grupo_vaos[0].id}",
			)

	# ------------------------------------------------------------------
	# link (excentricidade) -- só analítico, NUNCA gera elemento físico
	# (regra já fechada: Link e Restricao geram entidade analítica; Apoio
	# em si nunca gera nada)
	# ------------------------------------------------------------------

	def _escrever_link(self, link) -> None:
		no_ini = self._no_analitico(link.no_inicial, apoio=None)
		no_fim = self._no_analitico(link.no_final, apoio=None)

		barra_ifc = self._w.criar_entidade(
			"IFCSTRUCTURALCURVEMEMBER",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"barra:{link.id}"),
			OwnerHistory=None, Name=f"Link.{link.id}", Description=None, ObjectType=None,
			ObjectPlacement=None, Representation=None,
			# RIGID_JOINED_MEMBER (não PIN_JOINED_MEMBER): o Link transmite
			# momento e cortante, não só força axial -- mesmo a descrição
			# oficial do enum mencionando "viga" em vez de "conector rígido"
			PredefinedType=ValorEnum("RIGID_JOINED_MEMBER"), Axis=None,
		)
		for extremidade, no in (("ini", no_ini), ("fim", no_fim)):
			self._w.criar_entidade(
				"IFCRELCONNECTSSTRUCTURALMEMBER",
				GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"conecta:{link.id}:{extremidade}"),
				OwnerHistory=None, Name=None, Description=None,
				RelatingStructuralMember=barra_ifc, RelatedStructuralConnection=no,
				AppliedCondition=None, AdditionalConditions=None, SupportedLength=None,
				ConditionCoordinateSystem=None,
			)

	# ------------------------------------------------------------------
	# laje -- física: SEMPRE 1 único IfcSlab (seção/material sempre
	# constantes na Laje inteira, por isso nunca precisa agrupar como
	# Pilar/Viga); analítica: 1 IfcStructuralCurveMember por barra da
	# grelha (barras_grid_x + barras_grid_y), sem apoio/condição de
	# contorno própria (Barra de grid não carrega Apoio)
	# ------------------------------------------------------------------

	def _escrever_laje(self, laje) -> None:
		if laje.grelha is None or not laje.grelha.poligono:
			raise ValueError(
				f"Laje '{laje.nome}' sem grelha montada -- chame modelo.montar() "
				"antes de exportar."
			)

		barras_grid = list(laje.barras_grid_x) + list(laje.barras_grid_y)
		membros_analiticos: List[RefEntidadeIfc] = []
		for barra in barras_grid:
			no_ini = self._no_analitico(barra.no_inicial, apoio=None)
			no_fim = self._no_analitico(barra.no_final, apoio=None)
			barra_ifc = self._w.criar_entidade(
				"IFCSTRUCTURALCURVEMEMBER",
				GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"barra:{barra.id}"),
				OwnerHistory=None, Name=None, Description=None, ObjectType=None,
				ObjectPlacement=None, Representation=None,
				PredefinedType=ValorEnum("RIGID_JOINED_MEMBER"), Axis=None,
			)
			membros_analiticos.append(barra_ifc)
			for extremidade, no in (("ini", no_ini), ("fim", no_fim)):
				self._w.criar_entidade(
					"IFCRELCONNECTSSTRUCTURALMEMBER",
					GlobalId=guid_deterministico(
						NAMESPACE_PORTICO_ESPACIAL, f"conecta:{barra.id}:{extremidade}"
					),
					OwnerHistory=None, Name=None, Description=None,
					RelatingStructuralMember=barra_ifc, RelatedStructuralConnection=no,
					AppliedCondition=None, AdditionalConditions=None, SupportedLength=None,
					ConditionCoordinateSystem=None,
				)

		# física: sempre 1 único IfcSlab -- contorno (laje.grelha.poligono)
		# representa o TOPO da laje (confirmado), sólido extrudado PRA BAIXO
		# por laje.secao.altura (espessura). Só suporta laje horizontal (Z
		# constante no contorno) -- ver pendência no topo do arquivo.
		if not isinstance(laje.secao, SecaoRetangular):
			raise NotImplementedError(
				f"Geometria de sólido só implementada pra SecaoRetangular (Laje '{laje.nome}' "
				f"usa {type(laje.secao).__name__})."
			)
		poligono = laje.grelha.poligono
		z0 = poligono[0][2]
		if any(abs(p[2] - z0) > 1e-6 for p in poligono):
			raise NotImplementedError(
				f"Laje '{laje.nome}' não é horizontal (Z varia no contorno) -- geometria de "
				"sólido de laje inclinada não implementada nesta versão."
			)

		origem_ifc = self._w.criar_entidade("IFCCARTESIANPOINT", Coordinates=[0.0, 0.0, float(z0)])
		posicao_solido = self._w.criar_entidade(
			"IFCAXIS2PLACEMENT3D", Location=origem_ifc, Axis=None, RefDirection=None
		)
		placement = self._w.criar_entidade("IFCLOCALPLACEMENT", PlacementRelTo=None, RelativePlacement=posicao_solido)

		pontos_perfil = [
			self._w.criar_entidade("IFCCARTESIANPOINT", Coordinates=[float(x), float(y)]) for x, y, _z in poligono
		]
		contorno_ifc = self._w.criar_entidade("IFCPOLYLINE", Points=pontos_perfil + [pontos_perfil[0]])
		perfil = self._w.criar_entidade(
			"IFCARBITRARYCLOSEDPROFILEDEF", ProfileType=ValorEnum("AREA"), ProfileName=None,
			OuterCurve=contorno_ifc,
		)
		# extrusão PRA BAIXO (contorno = topo) -- Position fica com os eixos
		# globais padrão (identidade), então ExtrudedDirection=(0,0,-1) já
		# aponta pra baixo no mundo real
		direcao_extrusao = self._w.criar_entidade("IFCDIRECTION", DirectionRatios=[0.0, 0.0, -1.0])
		solido = self._w.criar_entidade(
			"IFCEXTRUDEDAREASOLID", SweptArea=perfil, Position=self._eixo_origem(),
			ExtrudedDirection=direcao_extrusao, Depth=float(laje.secao.altura),
		)
		representacao = self._w.criar_entidade(
			"IFCSHAPEREPRESENTATION", ContextOfItems=self._contexto_geometrico(),
			RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[solido],
		)
		forma = self._w.criar_entidade(
			"IFCPRODUCTDEFINITIONSHAPE", Name=None, Description=None, Representations=[representacao]
		)

		chave_guid = f"fisico:laje:{laje.id}"
		slab = self._w.criar_entidade(
			"IFCSLAB",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, chave_guid),
			OwnerHistory=None, Name=laje.nome, Description=None, ObjectType=None,
			ObjectPlacement=placement, Representation=forma,
			Tag=None, PredefinedType=ValorEnum("FLOOR"),
		)

		if membros_analiticos:
			self._w.criar_entidade(
				"IFCRELASSIGNSTOPRODUCT",
				GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"assign:{chave_guid}"),
				OwnerHistory=None, Name=None, Description=None,
				RelatedObjects=membros_analiticos, RelatedObjectsType=None, RelatingProduct=slab,
			)
		self._w.criar_entidade(
			"IFCRELCONTAINEDINSPATIALSTRUCTURE",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"contido:{chave_guid}"),
			OwnerHistory=None, Name=None, Description=None,
			RelatedElements=[slab], RelatingStructure=self._storey_de(laje.pavimento),
		)
		material_ifc = self._material_ifc(laje.material)
		self._w.criar_entidade(
			"IFCRELASSOCIATESMATERIAL",
			GlobalId=guid_deterministico(NAMESPACE_PORTICO_ESPACIAL, f"material:{chave_guid}"),
			OwnerHistory=None, Name=None, Description=None,
			RelatedObjects=[slab], RelatingMaterial=material_ifc,
		)
