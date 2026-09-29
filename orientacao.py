"""
Módulo de orientação e geometria da seção de uma barra no espaço.

Fonte ÚNICA da convenção de eixos locais e de como a seção transversal é
posicionada em torno do eixo da barra. Usado pelos exportadores
(ExportadorDxf, ExportadorIfc) e pela detecção de interseção
(interseccao.py), pra que desenho e detecção nunca divirjam entre si.

CONVENÇÃO PRÓPRIA DO PROJETO (derivada da do SAP2000, com um ajuste só no
caso vertical):

  eixo1 = ao longo da barra (no_inicial -> no_final)
  eixo2 = "pra cima": Z global projetado no plano perpendicular a eixo1.
          Se a barra é vertical (Z não tem projeção -- caso degenerado),
          usa Y global no lugar (o SAP2000 usa X aqui).
  eixo3 = eixo1 x eixo2
  `rotacao` (graus) gira eixo2/eixo3 em torno de eixo1.

  Regra ÚNICA pra qualquer orientação: ALTURA da seção -> eixo2 e
  LARGURA -> eixo3. Com isso, pilar vertical fica com altura em Y e
  largura em X (leitura de planta baixa), e a altura de Pilar e Viga fica
  consistente (nas duas é a dimensão ao longo do eixo2).

  Referência dos vértices da seção (`SecaoTransversal.vertices`): pares
  (largura, altura) em torno do ponto de referência da barra. O ponto de
  referência é o EIXO da barra (Pilar) ou o TOPO da seção (Viga e barras
  de grid da Laje -- ver `referencia_topo`).

ATENÇÃO na exportação pro SAP2000: essa convenção difere da dele só pra
barra vertical (SAP2000: eixo2 = X; aqui: eixo2 = Y) -- quem exportar pro
SAP2000 precisa compensar (ex.: rotação de 90° na barra vertical).

CAVEAT (seção assimétrica): a seção é desenhada "como vista olhando ao
longo da barra". Numa barra subindo em +Z isso faz a largura crescer pra
-X, então uma seção assimétrica (ex.: L) sai espelhada em X em relação à
planta vista de cima. Seções simétricas não são afetadas.
"""

from __future__ import annotations

import math
from typing import List, Tuple

from .geometria import Ponto
from .secoes import SecaoTransversal

Vetor2D = Tuple[float, float]
Vetor3D = Tuple[float, float, float]

# Barra "vertical" = eixo1 praticamente paralelo a Z (produto escalar com Z
# quase 1). Tolerância propositalmente apertada: só o caso degenerado de
# verdade troca o vetor de referência de eixo2.
_TOLERANCIA_VERTICAL = 1e-9


def eixos_locais(
    p_ini: Ponto, p_fim: Ponto, rotacao_graus: float = 0.0
) -> Tuple[Vetor3D, Vetor3D, Vetor3D, float]:
    """
    Base ortonormal local da barra de p_ini a p_fim, com a rotação própria
    aplicada. Retorna (eixo1, eixo2, eixo3, comprimento).
    """
    dx, dy, dz = p_fim.x - p_ini.x, p_fim.y - p_ini.y, p_fim.z - p_ini.z
    comprimento = math.sqrt(dx * dx + dy * dy + dz * dz)
    if comprimento < 1e-9:
        raise ValueError("Barra de comprimento nulo -- não dá pra orientar geometricamente.")
    e1 = (dx / comprimento, dy / comprimento, dz / comprimento)

    # Vetor de referência de eixo2: Z global, exceto na barra vertical, onde
    # a projeção de Z no plano perpendicular a eixo1 seria nula.
    barra_vertical = abs(e1[2]) > 1 - _TOLERANCIA_VERTICAL
    ref = (0.0, 1.0, 0.0) if barra_vertical else (0.0, 0.0, 1.0)

    # eixo2 (antes da rotação) = ref projetado no plano perpendicular a eixo1
    produto_escalar = ref[0] * e1[0] + ref[1] * e1[1] + ref[2] * e1[2]
    bruto = tuple(ref[i] - produto_escalar * e1[i] for i in range(3))
    norma = math.sqrt(sum(c * c for c in bruto))
    e2_0 = tuple(c / norma for c in bruto)

    # eixo3 (antes da rotação) = eixo1 x eixo2
    e3_0 = (
        e1[1] * e2_0[2] - e1[2] * e2_0[1],
        e1[2] * e2_0[0] - e1[0] * e2_0[2],
        e1[0] * e2_0[1] - e1[1] * e2_0[0],
    )

    # rotação de eixo2/eixo3 em torno de eixo1
    rad = math.radians(rotacao_graus)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    e2 = tuple(e2_0[i] * cos_r + e3_0[i] * sin_r for i in range(3))
    e3 = tuple(-e2_0[i] * sin_r + e3_0[i] * cos_r for i in range(3))

    return e1, e2, e3, comprimento


def vertices_anti_horario(vertices: List[Vetor2D]) -> List[Vetor2D]:
    """
    Garante sentido anti-horário (área com sinal positiva) -- pra que a
    normal das faces (MESH no DXF, perfil no IFC) saia consistente
    independente da ordem em que os vértices foram informados.
    """
    n = len(vertices)
    area_dupla = sum(
        vertices[i][0] * vertices[(i + 1) % n][1] - vertices[(i + 1) % n][0] * vertices[i][1]
        for i in range(n)
    )
    return vertices if area_dupla > 0 else list(reversed(vertices))


def perfil_local(secao: SecaoTransversal, referencia_topo: bool) -> List[Vetor2D]:
    """
    Contorno da seção como pares (largura, altura) em torno do ponto de
    referência da barra, em sentido anti-horário, sempre como float.

    `referencia_topo=True` (Viga, barras de grid da Laje): o ponto de
    referência da barra é o TOPO da seção, não o eixo -- desloca o perfil
    na direção da altura até seu ponto mais alto coincidir com a
    referência (em vez de ficar centrado nela). Funciona pra qualquer
    perfil (não só retangular): desloca pela altura máxima real dos
    vértices, não por altura/2 fixo.
    `referencia_topo=False` (Pilar): o perfil fica como veio de
    `secao.vertices`, sem deslocamento.

    Coage cada coordenada pra float: valores int (ex.: `(0, 0)` digitado
    à mão numa SecaoPoligonal) viram STEP com tipo errado no IFC.
    """
    vertices = [(float(vx), float(vy)) for vx, vy in secao.vertices]
    vertices = vertices_anti_horario(vertices)
    if referencia_topo:
        altura_maxima = max(vy for _vx, vy in vertices)
        vertices = [(vx, vy - altura_maxima) for vx, vy in vertices]
    return vertices


def extensoes_do_perfil(
    secao: SecaoTransversal, referencia_topo: bool
) -> Tuple[float, float, float, float]:
    """
    Caixa envolvente do perfil no referencial da barra:
    (largura_min, largura_max, altura_min, altura_max), relativa ao ponto
    de referência (já com o deslocamento de topo, se `referencia_topo`).
    """
    perfil = perfil_local(secao, referencia_topo)
    larguras = [vx for vx, _vy in perfil]
    alturas = [vy for _vx, vy in perfil]
    return min(larguras), max(larguras), min(alturas), max(alturas)


def prisma_global(
    p_ini: Ponto,
    p_fim: Ponto,
    rotacao_graus: float,
    secao: SecaoTransversal,
    referencia_topo: bool,
) -> Tuple[List[Vetor3D], List[Vetor3D]]:
    """
    Vértices, em coordenadas globais, das duas tampas do prisma formado
    pela seção extrudada de p_ini a p_fim: (tampa_inicial, tampa_final),
    cada uma na ordem de `perfil_local` (mesma ordem nas duas tampas).

    Cada vértice (largura, altura) do perfil vai pra
    `no + largura*eixo3 + altura*eixo2`.
    """
    _, e2, e3, _ = eixos_locais(p_ini, p_fim, rotacao_graus)
    perfil = perfil_local(secao, referencia_topo)

    def tampa(no: Ponto) -> List[Vetor3D]:
        return [
            (
                no.x + largura * e3[0] + altura * e2[0],
                no.y + largura * e3[1] + altura * e2[1],
                no.z + largura * e3[2] + altura * e2[2],
            )
            for largura, altura in perfil
        ]

    return tampa(p_ini), tampa(p_fim)
