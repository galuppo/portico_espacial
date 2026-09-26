"""
Ordem posicional dos atributos de cada entidade IFC usada pelo exportador do
Pórtico Espacial (schema IFC4).

Cada entrada é a lista de nomes de atributos NA ORDEM EXATA do schema
EXPRESS -- o formato STEP é posicional, não nomeado, então essa ordem tem
que estar certa pro arquivo ser lido corretamente por qualquer software IFC.

Cada bloco abaixo foi confirmado contra a especificação oficial da
buildingSMART (standards.buildingsmart.org, schema IFC4) e depois VALIDADO
por execução: um arquivo .ifc de teste cobrindo todos os blocos foi gerado
e aberto com sucesso pelo ifcopenshell, incluindo geração da geometria
tesselada real (não só o parsing textual).

IMPORTANTE: um atributo marcado como DERIVADO no schema EXPRESS (ex.:
IfcSIUnit.Dimensions) NÃO entra nessa lista -- ele não é armazenado, e o
EscritorIfcManual escreve "*" nessa posição em vez de um valor (ver
tratamento especial em EscritorIfcManual.criar_entidade).
"""

from typing import Dict, List

ORDEM_ATRIBUTOS: Dict[str, List[str]] = {

	# -- bloco 1: estrutura espacial e unidades -----------------------------
	"IFCPROJECT": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"ObjectType", "LongName", "Phase",
		"RepresentationContexts", "UnitsInContext",
	],
	"IFCSITE": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"ObjectType", "ObjectPlacement", "Representation",
		"LongName", "CompositionType",
		"RefLatitude", "RefLongitude", "RefElevation",
		"LandTitleNumber", "SiteAddress",
	],
	"IFCBUILDING": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"ObjectType", "ObjectPlacement", "Representation",
		"LongName", "CompositionType",
		"ElevationOfRefHeight", "ElevationOfTerrain", "BuildingAddress",
	],
	"IFCBUILDINGSTOREY": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"ObjectType", "ObjectPlacement", "Representation",
		"LongName", "CompositionType", "Elevation",
	],
	"IFCRELAGGREGATES": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"RelatingObject", "RelatedObjects",
	],
	"IFCUNITASSIGNMENT": ["Units"],
	# IfcSIUnit.Dimensions é DERIVADO -- ver nota no topo do arquivo
	"IFCSIUNIT": ["UnitType", "Prefix", "Name"],

	# -- bloco 2: geometria de apoio -----------------------------------------
	"IFCCARTESIANPOINT": ["Coordinates"],
	"IFCDIRECTION": ["DirectionRatios"],
	"IFCAXIS2PLACEMENT3D": ["Location", "Axis", "RefDirection"],
	"IFCLOCALPLACEMENT": ["PlacementRelTo", "RelativePlacement"],

	# -- bloco 3: camada analítica -------------------------------------------
	"IFCSTRUCTURALPOINTCONNECTION": [
		"GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
		"ObjectPlacement", "Representation",
		"AppliedCondition", "ConditionCoordinateSystem",
	],
	"IFCSTRUCTURALCURVEMEMBER": [
		"GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
		"ObjectPlacement", "Representation",
		"PredefinedType", "Axis",
	],
	"IFCBOUNDARYNODECONDITION": [
		"Name",
		"TranslationalStiffnessX", "TranslationalStiffnessY", "TranslationalStiffnessZ",
		"RotationalStiffnessX", "RotationalStiffnessY", "RotationalStiffnessZ",
	],
	"IFCRELCONNECTSSTRUCTURALMEMBER": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"RelatingStructuralMember", "RelatedStructuralConnection",
		"AppliedCondition", "AdditionalConditions", "SupportedLength", "ConditionCoordinateSystem",
	],

	# -- bloco 4: camada física -----------------------------------------------
	"IFCCOLUMN": [
		"GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
		"ObjectPlacement", "Representation", "Tag", "PredefinedType",
	],
	"IFCBEAM": [
		"GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
		"ObjectPlacement", "Representation", "Tag", "PredefinedType",
	],
	"IFCSLAB": [
		"GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
		"ObjectPlacement", "Representation", "Tag", "PredefinedType",
	],
	"IFCARBITRARYCLOSEDPROFILEDEF": ["ProfileType", "ProfileName", "OuterCurve"],
	"IFCPOLYLINE": ["Points"],
	"IFCEXTRUDEDAREASOLID": ["SweptArea", "Position", "ExtrudedDirection", "Depth"],
	"IFCSHAPEREPRESENTATION": ["ContextOfItems", "RepresentationIdentifier", "RepresentationType", "Items"],
	"IFCPRODUCTDEFINITIONSHAPE": ["Name", "Description", "Representations"],
	"IFCGEOMETRICREPRESENTATIONCONTEXT": [
		"ContextIdentifier", "ContextType", "CoordinateSpaceDimension",
		"Precision", "WorldCoordinateSystem", "TrueNorth",
	],
	"IFCRELASSIGNSTOPRODUCT": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"RelatedObjects", "RelatedObjectsType", "RelatingProduct",
	],

	# -- bloco 5: materiais + contenção espacial -------------------------------
	"IFCRELCONTAINEDINSPATIALSTRUCTURE": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"RelatedElements", "RelatingStructure",
	],
	"IFCMATERIAL": ["Name", "Description", "Category"],
	"IFCRELASSOCIATESMATERIAL": [
		"GlobalId", "OwnerHistory", "Name", "Description",
		"RelatedObjects", "RelatingMaterial",
	],
}

# Tipos cujo primeiro atributo é DERIVADO (schema EXPRESS) e por isso deve
# ser escrito como "*" em vez de consultar ORDEM_ATRIBUTOS/atributos
# fornecidos. Hoje só IfcSIUnit tem esse caso no escopo do exportador.
ENTIDADES_COM_ATRIBUTO_DERIVADO_INICIAL = {"IFCSIUNIT"}
