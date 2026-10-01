# Pórtico Espacial

Modelo de dados em Python para descrever **pórticos espaciais de concreto armado** (pilares, vigas e lajes), **independente de qualquer software de análise**.

O modelo de domínio não conhece o SAP2000, o DXF ou o IFC. Cada formato de saída é um *adaptador* isolado em `exportadores/`, o que permite reutilizar o mesmo modelo com outros alvos no futuro.

> **Status:** em desenvolvimento. A fase de **modelagem** e os exportadores **DXF** e **IFC** estão implementados. Análise, dimensionamento, detalhamento e exportação para o SAP2000 ainda não (ver [Status](#status)).

---

## Sumário

- [Principais características](#principais-características)
- [Status](#status)
- [Instalação](#instalação)
- [Exemplo de uso](#exemplo-de-uso)
- [Conceitos e arquitetura](#conceitos-e-arquitetura)
- [Convenções do projeto](#convenções-do-projeto)
- [Exportadores](#exportadores)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Limitações conhecidas](#limitações-conhecidas)
- [Licença](#licença)

---

## Principais características

- Lançamento de **Pilares, Vigas e Lajes por coordenadas**, amarrados a **Pavimentos** registrados no modelo.
- **Detecção automática de interseções** considerando a **seção real** dos elementos (Viga × Pilar, Viga × Viga) e de **apoio de Laje em Vão** de viga.
- Derivação automática de **Lances** (trechos de pilar), **Vãos** (trechos de viga), **Apoios** e **Links** (conectores rígidos para excentricidades).
- **Laje como grelha**: malha ortogonal gerada sobre a poligonal da laje, com coeficientes de carga (área de influência) por nó.
- Seções transversais **retangulares** e **poligonais** (área e inércias calculadas pelas fórmulas de polígono).
- Propriedades do **concreto conforme a NBR 6118** (`fck`, `fcd`, `fctm`, `Eci`, `Ecs`, `fcj`...).
- Exportação para **DXF 3D** (linhas ou sólidos) e **IFC4** (camadas analítica e física), sem depender do `ifcopenshell`.

---

## Status

| Fase / módulo | Situação |
|---|---|
| Modelagem (`ModeloPortico.montar()`) | Implementada |
| Interseção Viga × Pilar (pilar vertical) | Implementada |
| Interseção Viga × Pilar (pilar inclinado) | Pendente (`NotImplementedError`) |
| Interseção Viga × Viga (viga sem rotação própria) | Implementada |
| Apoio de Laje em Vão | Implementado |
| Exportador DXF | Implementado |
| Exportador IFC4 | Implementado |
| Exportador SAP2000 | Pendente (esqueleto) |
| Análise (`AnalisePortico`) | Pendente |
| Dimensionamento NBR 6118 (`DimensionamentoPortico`) | Pendente |
| Detalhamento (`DetalhamentoPortico`) | Pendente |

---

## Instalação

**Requisitos**

- Python **3.10 ou superior** (o código usa `match/case` e a sintaxe `X | None`). <!-- CONFIRMAR versão mínima -->
- [`numpy`](https://numpy.org/) (geração da grelha das lajes)
- [`ezdxf`](https://ezdxf.mozman.at/) (exportador DXF)

```bash
git clone https://github.com/<usuario>/<repositorio>.git
cd <repositorio>
pip install numpy ezdxf
```

<!-- CONFIRMAR: nome do repositório/pacote e se haverá pyproject.toml / requirements.txt -->

O `ifcopenshell` **não** é necessário para exportar IFC (a escrita STEP é feita manualmente). Ele é útil apenas para validar/visualizar os arquivos gerados.

---

## Exemplo de uso

Pórtico simples: dois pilares engastados na base e uma viga entre eles.

```python
from portico_espacial.concreto import Concreto, TipoAgregado
from portico_espacial.elementos import ApoioRestricao
from portico_espacial.estrutura import ModeloPortico
from portico_espacial.geometria import Ponto
from portico_espacial.secoes import SecaoRetangular
from portico_espacial.vinculos import Restricao

# 1) Modelo e pavimentos (devem existir ANTES de qualquer elemento)
modelo = ModeloPortico()
terreo = modelo.criar_pavimento("Terreo", elevacao=0.0)
pav1 = modelo.criar_pavimento("Pav1", elevacao=3.0)

# 2) Material (NBR 6118) e seções
c30 = Concreto(fck_MPa=30.0, agregado=TipoAgregado.BASALTO_DIABASIO, nome="C30")
secao_pilar = SecaoRetangular(largura=0.30, altura=0.50)
secao_viga = SecaoRetangular(largura=0.20, altura=0.50)

# 3) Pilares (base no Térreo, topo no Pav1) com fundação engastada
for x in (0.0, 5.0):
    pilar = modelo.criar_pilar(
        pavimento_base=terreo, x_base=x, y_base=0.0,
        pavimento_topo=pav1, x_topo=x, y_topo=0.0,
        secao=secao_pilar, material=c30,
    )
    pilar.apoio_base = ApoioRestricao(Restricao.engastado(pilar.ponto_base))

# 4) Viga: os pontos representam o TOPO da seção (ver Convenções)
modelo.criar_viga(
    ponto_inicial=Ponto(0.0, 0.0, 3.0),
    ponto_final=Ponto(5.0, 0.0, 3.0),
    secao=secao_viga, material=c30,
    pavimentos=[pav1],
)

# 5) Resolve interseções e deriva Lances, Vãos, Apoios e Links
modelo.montar()

# 6) Exportação
from portico_espacial.exportadores.dxf import ExportadorDxf
from portico_espacial.exportadores.ifc import EscritorIfcManual, ExportadorIfc

ExportadorDxf().exportar_solido(modelo, "portico.dxf")
ExportadorIfc(modelo, EscritorIfcManual()).exportar("portico.ifc")
```

> Os nomes de módulo acima (`portico_espacial`) são provisórios. Ajuste conforme o nome real do pacote. <!-- CONFIRMAR -->

Se houver qualquer excentricidade real no modelo, configure antes de `montar()`:

```python
modelo.secao_link = SecaoRetangular(largura=0.05, altura=0.05)  # seção pequena
modelo.material_link = <Material com módulo de elasticidade muito alto>  # aproxima um conector rígido
```

---

## Conceitos e arquitetura

### Hierarquia de elementos

```
ElementoEstrutural (ABC)   -- todo elemento retorna suas Barras atômicas via .barras()
│
├── Barra (ABC)            -- 2 nós, seção, material, rotação
│    ├── Lance             -- trecho de um Pilar entre duas quebras
│    ├── Vao               -- trecho de uma Viga entre dois pontos de quebra
│    └── Link              -- conector rígido para excentricidade
│
├── Pilar                  -- agregador de Lances (não é uma Barra)
├── Viga                   -- agregador de Vãos (não é uma Barra)
└── Laje                   -- agregadora das barras de grid (não é uma Barra)
```

### Fluxo em 4 fases

O orquestrador `Portico` coordena:

1. **Modelagem** (`ModeloPortico`): geometria, interseções, Lances/Vãos/Apoios/Links.
2. **Análise** (`AnalisePortico`): esforços e deslocamentos por id de Barra.
3. **Dimensionamento** (`DimensionamentoPortico`): armaduras e verificações da NBR 6118.
4. **Detalhamento** (`DetalhamentoPortico`): documentação por Pavimento.

### Apoios

`Apoio` tem duas variantes:

- `ApoioElemento`: apoio em outro elemento real do modelo (Pilar ou Viga).
- `ApoioRestricao`: apoio como condição de contorno simplificada (`Restricao`, 6 graus de liberdade), para fundação não modelada ou elementos isolados.

A **existência** de uma conexão Viga × Viga é determinada só pela geometria; a **direção** (quem se apoia em quem) fica para o detalhamento. Lajes se apoiam em **Vãos**, por meio de `ApoioLaje` (trecho da aresta + intervalo), inferido em `montar()`.

### Identificadores

- **`id`**: numérico, vindo de um contador global único para todo elemento. É **permanente** e serve de chave técnica (e de *label* em exportações).
- **`nome`**: rótulo de documentação com prefixo (`P1`, `V1`, `LJ1`). Pode ser renovado sem afetar o `id`. O nome de `Lance`/`Vao` é derivado do elemento pai (ex.: `P1.2`).

---

## Convenções do projeto

- **Viga**: `ponto_inicial`/`ponto_final` representam o **topo** da seção, não o eixo centroidal. A faixa vertical da viga é `[z − altura, z]`. O ajuste para o eixo centroidal é responsabilidade dos exportadores.
- **Laje**: o polígono representa o **topo** da laje; o sólido é extrudado **para baixo** pela espessura.
- **Pilar**: definido por Pavimento de base/topo + posição em planta + desnível opcional; a cota é `pavimento.elevacao + desnivel`.
- **Eixos locais da barra** (definidos em `orientacao.py`, fonte única para detecção e exportação):
  - `eixo1`: ao longo da barra; `eixo2`: "para cima" (Z global projetado; Y global se a barra for vertical); `eixo3 = eixo1 × eixo2`.
  - **Altura** da seção → `eixo2`; **largura** → `eixo3`. `rotacao` (graus) gira `eixo2`/`eixo3` em torno de `eixo1`.
  - Difere do SAP2000 **apenas** para barra vertical (SAP2000 usa X no lugar de Y); o exportador para SAP2000 deverá compensar.
- **Unidades**: o modelo opera em **metros**. Um conversor de unidades ainda não existe.

---

## Exportadores

### DXF (`exportadores/dxf.py`)

Gera DXF 3D para **inspeção visual** em qualquer CAD (não é para análise).

- `exportar()`: cada Barra como `LINE`.
- `exportar_solido()`: cada Barra como sólido extrudado (`MESH` fechada) pela seção real.
- Layers por **Pavimento + tipo** (ex.: `PAV1-PILARES`), rótulos com id e nome, símbolos de apoio conforme o tipo de restrição (engastado, simples, elástico, misto).
- Parâmetro opcional `pavimento` para exportar um único pavimento.

### IFC4 (`exportadores/ifc/`)

- Duas camadas ligadas por `IfcRelAssignsToProduct`: **analítica** (`IfcStructuralCurveMember` + `IfcStructuralPointConnection`, com `IfcBoundaryNodeCondition`) e **física** (`IfcColumn`, `IfcBeam`, `IfcSlab` com geometria `IfcExtrudedAreaSolid`).
- Estrutura espacial (`IfcBuildingStorey` por Pavimento) e `IfcMaterial` deduplicado por nome.
- **GUIDs determinísticos**: a reexportação gera os mesmos identificadores.
- Escrita STEP manual (`EscritorIfcManual`), sem `ifcopenshell`.

### SAP2000 (`exportadores/sap2000.py`)

Apenas o esqueleto da classe (`NotImplementedError`). Está prevista a exportação via OAPI, usando o `id` de cada Barra como *label*.

---

## Estrutura do projeto

```
.
├── __init__.py
├── geometria.py        # Ponto e tolerância geométrica
├── materiais.py        # Material
├── concreto.py         # Concreto (NBR 6118)
├── secoes.py           # SecaoTransversal, SecaoRetangular, SecaoPoligonal
├── vinculos.py         # Restricao e graus de liberdade
├── identificadores.py  # GeradorId (id permanente e nome de documentação)
├── orientacao.py       # Eixos locais e geometria da seção
├── grelha.py           # Malha ortogonal da laje e coeficientes de carga
├── elementos.py        # Barra, Lance, Vao, Link, Pilar, Viga, Laje, Apoios
├── interseccao.py      # Detecção de interseções e apoios
├── estrutura.py        # ModeloPortico, AnalisePortico, DimensionamentoPortico, Portico
├── detalhamento.py     # DetalhamentoPortico
└── exportadores/
    ├── dxf.py
    ├── sap2000.py
    └── ifc/
        ├── escritor.py
        ├── ordem_atributos.py
        └── exportador.py
```

<!-- CONFIRMAR: ajustar a árvore conforme a organização real do repositório (inclusive exemplos e logger, se forem incluídos) -->

---

## Limitações conhecidas

- Interseção com **pilar inclinado** não implementada.
- Interseção Viga × Viga assume **viga sem rotação própria** (altura sempre vertical).
- **Laje inclinada**: a `Grelha` suporta planos inclinados, mas o sólido físico no IFC exige laje horizontal.
- Geometria de sólido da **laje** exige `SecaoRetangular`.
- **Viga cruzando o interior de uma laje** ainda não gera erro de validação.
- Vigas criadas **sem `pavimentos`** são ignoradas na resolução de apoios de laje.
- Viga **curva** fora do escopo inicial.
- Seções assimétricas em pilar vertical saem espelhadas em X em relação à leitura de planta (seções simétricas não são afetadas).
- Conversor de unidades inexistente (somente metros).
- A detecção Viga × Pilar ainda testa todos os pares (O(n×m)), sem otimização por pavimento.

---

## Licença

<!-- CONFIRMAR: definir a licença do projeto -->
A definir.
