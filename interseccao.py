"""
Módulo de detecção de interseção entre elementos do Pórtico Espacial.

Usado na montagem do ModeloPortico para descobrir onde uma Viga cruza
um Pilar (ou outra Viga), considerando a seção real do elemento
hospedeiro -- não apenas a reta idealizada do eixo.

Funciona com qualquer SecaoTransversal (SecaoRetangular, SecaoPoligonal...):
a geometria da seção vem de `orientacao.py`, a mesma fonte usada pelos
exportadores -- assim o que a detecção considera "dentro da seção" é
exatamente o que é desenhado.

ESCOPO ATUAL:
  - Viga x Pilar: só Pilar vertical está implementado. Pilar inclinado
    (_intersecao_pilar_generico) levanta NotImplementedError -- fica
    para depois de validar o caminho simplificado em uso real. Contato
    aproximado pelo alcance de cada seção (mesmo critério de Viga x
    Viga, não o polígono exato): qualquer toque entre a seção do Pilar
    e a seção da Viga, não só o eixo da Viga caindo dentro do Pilar.
  - Viga x Viga: assume Viga sem rotação própria (altura sempre
    vertical, ao longo de Z global) -- viga rotacionada fica para
    depois. Contato aproximado pelo alcance da seção de cada viga:
    alcance lateral (em planta) e faixa vertical.

  - Laje x Vão: detectar_apoio_laje_em_vao -- aresta do polígono da Laje sobre o eixo
    do Vão (planta, com tolerância) e dentro da altura da viga; aceita Vão inclinado.

CONVENÇÃO DE REFERÊNCIA VERTICAL: ponto_inicial/ponto_final de uma
Viga representam o TOPO da seção, não o centroide -- decisão de
projeto, para simplificar modelagem/detalhamento (e viabilizar
desníveis de viga em relação ao pavimento como um simples ajuste de
z). A faixa de altura de uma viga é, portanto, [z - altura, z], não
[z - altura/2, z + altura/2] (pra seção não retangular, "altura" é a
extensão vertical do perfil). O ajuste para eixo centroidal (o que
ferramentas de análise como SAP2000/OpenSees esperam) é feito só na
exportação (exportadores/), não aqui.

A existência de uma conexão Viga x Viga é determinada inteiramente
pelo teste geométrico aqui (seção real de ambas as vigas) -- não
depende de nenhuma declaração prévia. Quando as faixas
de altura se sobrepõem mas os pontos de referência estão em cotas
diferentes, a conexão precisa de um Link (ver
ResultadoIntersecaoVigaViga.precisa_link).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .elementos import Pilar, Vao, Viga
from .geometria import TOLERANCIA_GEOMETRICA, Ponto
from .orientacao import extensoes_do_perfil


@dataclass(frozen=True)
class ResultadoIntersecao:
    """
    Resultado de uma interseção Viga x Pilar detectada.

    ponto_no_hospedeiro: ponto sobre o eixo do Pilar, na cota da
        conexão -- é o ponto que vira quebra de Lance no Pilar.
    ponto_no_dependente: ponto sobre o eixo da Viga, no plano de
        interseção -- é o ponto que vira nó no Vão da Viga.
    excentricidade: vetor (dx, dy), no plano local da seção do Pilar
        (já descontada a rotação do Pilar), entre os dois pontos
        acima. (0, 0) significa sem excentricidade -- não precisa de
        Link. Qualquer outro valor -- precisa.
    """

    ponto_no_hospedeiro: Ponto
    ponto_no_dependente: Ponto
    excentricidade: tuple[float, float]


def eh_vertical(pilar: Pilar) -> bool:
    """
    Um Pilar é vertical se a projeção em planta (x, y) da base e do
    topo coincidem.

    Comparação exata (sem tolerância) -- assume que as coordenadas do
    modelo já vêm exatas o suficiente (decisão de projeto).
    """
    return (
        pilar.ponto_base.x == pilar.ponto_topo.x
        and pilar.ponto_base.y == pilar.ponto_topo.y
    )


def _ponto_mais_proximo_em_planta(viga: Viga, x0: float, y0: float) -> Ponto:
    """
    Encontra o ponto ao longo do eixo da Viga cuja projeção em planta
    (x, y) é a mais próxima do ponto (x0, y0) -- projeção ortogonal de
    um ponto sobre um segmento de reta em 2D (produto escalar),
    limitada ao trecho real da viga (t entre 0 e 1).

    Retorna o Ponto 3D correspondente (com a cota z interpolada ao
    longo do eixo da viga nesse mesmo t).
    """
    p0, p1 = viga.ponto_inicial, viga.ponto_final
    dx, dy = p1.x - p0.x, p1.y - p0.y
    comprimento_quadrado = dx * dx + dy * dy

    if comprimento_quadrado == 0:
        # Viga com projeção em planta nula (ex.: viga vertical) -- sem
        # direção definida em planta; usa o ponto inicial.
        t = 0.0
    else:
        t = ((x0 - p0.x) * dx + (y0 - p0.y) * dy) / comprimento_quadrado
        t = max(0.0, min(1.0, t))  # limita ao segmento real, não à reta infinita
    return Ponto(
        x=p0.x + t * dx,
        y=p0.y + t * dy,
        z=p0.z + t * (p1.z - p0.z),
    )


def _alcance_radial_planta(secao) -> float:
    """
    Maior distância do ponto de referência da barra até a borda da seção,
    EM PLANTA -- usado só pro Pilar (vertical): como as duas dimensões da
    seção (`largura` e `altura`) ficam no plano horizontal, soma os dois
    lados de cada uma pra um raio conservador (cobre a seção inteira,
    independente de rotação).
    """
    largura_min, largura_max, altura_min, altura_max = extensoes_do_perfil(secao, referencia_topo=False)
    return max(abs(largura_min), abs(largura_max), abs(altura_min), abs(altura_max))


def _alcance_lateral_viga(secao) -> float:
    """
    Alcance em planta de uma Viga: só `largura` conta (`altura` é
    vertical pra uma viga horizontal, não faz parte do plano) -- mesmo
    critério já usado em `detectar_intersecao_viga_viga`.
    """
    largura_min, largura_max, _altura_min, _altura_max = extensoes_do_perfil(secao, referencia_topo=True)
    return max(abs(largura_min), abs(largura_max))


def _intersecao_pilar_vertical(viga: Viga, pilar: Pilar) -> ResultadoIntersecao | None:
    """
    Caminho simplificado: Pilar vertical.

    A extensão transversal do Pilar é, em qualquer cota da sua altura, a
    mesma em planta -- não precisa de nenhuma álgebra de retas reversas
    nem de plano perpendicular ao eixo; a "seção do Pilar" já É um plano
    horizontal.

    Contato aproximado pelo alcance de cada seção (mesmo padrão de
    Viga x Viga, não o polígono exato): a distância entre o centroide do
    Pilar e o ponto do eixo da Viga mais próximo dele precisa ser menor
    que a soma dos alcances -- ou seja, qualquer toque entre as duas
    seções, não só o eixo da Viga caindo dentro do Pilar.
    """
    x0, y0 = pilar.ponto_base.x, pilar.ponto_base.y
    ponto_viga = _ponto_mais_proximo_em_planta(viga, x0, y0)

    z_min, z_max = sorted((pilar.ponto_base.z, pilar.ponto_topo.z))
    if not (z_min <= ponto_viga.z <= z_max):
        return None  # ponto de aproximação mínima fora da faixa de altura do pilar

    distancia_em_planta = math.hypot(ponto_viga.x - x0, ponto_viga.y - y0)
    limite = _alcance_radial_planta(pilar.secao) + _alcance_lateral_viga(viga.secao)
    if distancia_em_planta > limite:
        return None  # a viga passa perto, mas longe demais -- sem conexão real

    # ponto de conexão: sobre o eixo da Viga (reta que a define), no ponto
    # de menor distância até o centroide do Pilar -- já é `ponto_viga`
    ponto_no_pilar = Ponto(x0, y0, ponto_viga.z)
    excentricidade = (ponto_viga.x - x0, ponto_viga.y - y0)
    return ResultadoIntersecao(
        ponto_no_hospedeiro=ponto_no_pilar,
        ponto_no_dependente=ponto_viga,
        excentricidade=excentricidade,
    )


def _intersecao_pilar_generico(viga: Viga, pilar: Pilar) -> ResultadoIntersecao | None:
    """
    Caminho geral, para Pilar inclinado.

    Resolveria a aproximação mínima entre duas retas reversas no
    espaço (eixo do Pilar x eixo da Viga) e a interseção reta-plano na
    seção do Pilar, usando o vetor diretor real do Pilar como normal
    do plano de corte (mesma ideia do método de Newell já usado na
    Grelha).

    AINDA NÃO IMPLEMENTADO -- decisão de projeto: validar o caminho
    simplificado (Pilar vertical) antes de generalizar.
    """
    raise NotImplementedError(
        "Interseção com Pilar inclinado ainda não implementada."
    )


def detectar_intersecao_viga_pilar(viga: Viga, pilar: Pilar) -> ResultadoIntersecao | None:
    """
    Ponto de entrada público: detecta se e onde uma Viga cruza um
    Pilar, considerando a seção real do Pilar.

    Retorna None se não há interseção real (viga passa longe demais em
    planta, ou fora da faixa de altura do pilar).
    """
    if eh_vertical(pilar):
        return _intersecao_pilar_vertical(viga, pilar)
    return _intersecao_pilar_generico(viga, pilar)


@dataclass(frozen=True)
class ResultadoIntersecaoVigaViga:
    """
    Resultado de uma interseção Viga x Viga detectada.

    Sem hierarquia (dependente/hospedeira) -- isso é decisão do
    DetalhamentoPortico, não da geometria.

    ponto_viga1 / ponto_viga2: pontos sobre o eixo de referência (topo
        da seção, ver docstring do módulo) de cada viga, na interseção
        -- cada um vira nó no Vão da viga correspondente.
    precisa_link: True quando os pontos de referência estão em cotas
        diferentes (ex.: profundidades diferentes) -- nesse caso, um
        Link deve conectar ponto_viga1 a ponto_viga2. Quando False, os
        dois pontos coincidem -- é o mesmo nó, sem necessidade de Link.
    """

    ponto_viga1: Ponto
    ponto_viga2: Ponto
    precisa_link: bool


def _interpolar_viga(viga: Viga, t: float) -> Ponto:
    """Ponto sobre o eixo da viga no parâmetro t (0 = ponto_inicial, 1 = ponto_final)."""
    p0, p1 = viga.ponto_inicial, viga.ponto_final
    return Ponto(
        x=p0.x + t * (p1.x - p0.x),
        y=p0.y + t * (p1.y - p0.y),
        z=p0.z + t * (p1.z - p0.z),
    )


def _pontos_mais_proximos_entre_segmentos_2d(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> tuple[float, float]:
    """
    Encontra os parâmetros (s, t), cada um limitado a [0, 1], que
    minimizam a distância entre o segmento p1->p2 e o segmento
    q1->q2, no plano (x, y).

    Algoritmo padrão de geometria computacional para aproximação
    mínima entre dois segmentos de reta (adaptado de "Real-Time
    Collision Detection", Ericson -- ClosestPtSegmentSegment,
    simplificado para 2D).
    """
    d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
    d2x, d2y = q2[0] - q1[0], q2[1] - q1[1]
    rx, ry = p1[0] - q1[0], p1[1] - q1[1]

    a = d1x * d1x + d1y * d1y  # |d1|^2
    e = d2x * d2x + d2y * d2y  # |d2|^2
    f = d2x * rx + d2y * ry

    eps = 1e-12

    if a <= eps and e <= eps:
        return 0.0, 0.0  # os dois segmentos são, na prática, pontos

    if a <= eps:
        # p1->p2 é degenerado (comprimento ~0)
        s = 0.0
        t = min(1.0, max(0.0, f / e))
        return s, t

    c = d1x * rx + d1y * ry

    if e <= eps:
        # q1->q2 é degenerado
        t = 0.0
        s = min(1.0, max(0.0, -c / a))
        return s, t

    b = d1x * d2x + d1y * d2y
    denom = a * e - b * b

    s = min(1.0, max(0.0, (b * f - c * e) / denom)) if denom != 0.0 else 0.0
    t = (b * s + f) / e

    if t < 0.0:
        t = 0.0
        s = min(1.0, max(0.0, -c / a))
    elif t > 1.0:
        t = 1.0
        s = min(1.0, max(0.0, (b - c) / a))

    return s, t


def detectar_intersecao_viga_viga(viga1: Viga, viga2: Viga) -> ResultadoIntersecaoVigaViga | None:
    """
    Detecta se e onde duas Vigas se cruzam de verdade, considerando a
    seção real de ambas: alcance lateral em planta + faixa vertical, os
    dois tirados da caixa envolvente do perfil de cada viga (funciona com
    qualquer SecaoTransversal).

    Retorna None se as vigas não chegam a se tocar -- seja porque
    passam longe demais em planta, seja porque suas faixas de altura
    não se sobrepõem (uma passa por baixo da outra, sem contato real).

    ESCOPO ATUAL: assume Viga sem rotação própria (altura sempre
    vertical, ao longo de Z global) -- ver módulo.
    """
    # Caixa envolvente do perfil de cada viga, com o TOPO como referência
    # (ver docstring do módulo): (largura_min, largura_max, altura_min, altura_max)
    _, _, altura_min1, altura_max1 = extensoes_do_perfil(viga1.secao, referencia_topo=True)
    _, _, altura_min2, altura_max2 = extensoes_do_perfil(viga2.secao, referencia_topo=True)

    p1 = (viga1.ponto_inicial.x, viga1.ponto_inicial.y)
    p2 = (viga1.ponto_final.x, viga1.ponto_final.y)
    q1 = (viga2.ponto_inicial.x, viga2.ponto_inicial.y)
    q2 = (viga2.ponto_final.x, viga2.ponto_final.y)

    s, t = _pontos_mais_proximos_entre_segmentos_2d(p1, p2, q1, q2)
    ponto1 = _interpolar_viga(viga1, s)
    ponto2 = _interpolar_viga(viga2, t)

    distancia_em_planta = math.hypot(ponto1.x - ponto2.x, ponto1.y - ponto2.y)
    # Alcance lateral = maior distância do eixo a qualquer lado da seção.
    # A distância entre os eixos não diz de que lado do eixo está o outro,
    # então usa o alcance dos dois lados (conservador quando a seção é
    # assimétrica; igual a largura/2 numa seção simétrica).
    alcance1 = _alcance_lateral_viga(viga1.secao)
    alcance2 = _alcance_lateral_viga(viga2.secao)
    limite = alcance1 + alcance2
    if distancia_em_planta > limite:
        return None  # nem chegam perto o suficiente em planta

    # ponto.z é o TOPO da viga (ver docstring do módulo): a faixa vertical
    # é a extensão do perfil (já deslocada pro topo, então altura_max = 0)
    topo1, fundo1 = ponto1.z + altura_max1, ponto1.z + altura_min1
    topo2, fundo2 = ponto2.z + altura_max2, ponto2.z + altura_min2
    if topo1 < fundo2 or topo2 < fundo1:
        return None  # faixas de altura não se sobrepõem -- sem contato real

    return ResultadoIntersecaoVigaViga(
        ponto_viga1=ponto1,
        ponto_viga2=ponto2,
        precisa_link=(ponto1.z != ponto2.z),
    )


def detectar_intersecoes_viga_viga_por_pavimento(
    vigas: list[Viga],
) -> list[tuple[Viga, Viga, ResultadoIntersecaoVigaViga]]:
    """
    Detecta todas as interseções Viga x Viga entre uma lista de Vigas,
    otimizando a busca de duas formas:

    1. Só testa pares de vigas que compartilham pelo menos um
       Pavimento (usando Viga.pavimentos -- a lista-resumo já
       atribuída a cada viga). Uma viga inclinada, que pertence a
       vários pavimentos, aparece em vários grupos e é testada contra
       as vigas de cada um.
    2. Cada par de vigas é testado no máximo uma vez -- se V1 x V3 já
       foi testado (num grupo), não é testado de novo (nem no mesmo
       grupo, nem em outro pavimento que as duas porventura
       compartilhem também).

    Sem essas otimizações, o teste seria O(n²) sobre TODAS as vigas do
    modelo; com elas, cada teste só compete com vigas do mesmo andar.
    """
    grupos_por_pavimento: dict[str, list[Viga]] = {}
    for viga in vigas:
        for pavimento in viga.pavimentos:
            grupos_por_pavimento.setdefault(pavimento.nome, []).append(viga)

    pares_ja_testados: set[frozenset[str]] = set()
    resultados: list[tuple[Viga, Viga, ResultadoIntersecaoVigaViga]] = []

    for grupo in grupos_por_pavimento.values():
        for i in range(len(grupo)):
            for j in range(i + 1, len(grupo)):
                viga1, viga2 = grupo[i], grupo[j]
                par = frozenset((viga1.id, viga2.id))
                if par in pares_ja_testados:
                    continue
                pares_ja_testados.add(par)

                resultado = detectar_intersecao_viga_viga(viga1, viga2)
                if resultado is not None:
                    resultados.append((viga1, viga2, resultado))

    return resultados


# Abaixo disso, a variação de cota relativa (g1) entre aresta e Vão é tratada como nula
# (aresta e Vão paralelos em elevação) -- evita divisão por ~0 ao resolver a faixa de altura.
_EPS_DECLIVIDADE = 1e-12


def detectar_apoio_laje_em_vao(
    aresta_inicial: Ponto, aresta_final: Ponto, vao: Vao
) -> tuple[float, float] | None:
    """
    Detecta se uma aresta do polígono de uma Laje se apoia (total ou
    parcialmente) num Vão de Viga.

    Critério de apoio (decisão de projeto): a aresta precisa estar
      1. SOBRE O EIXO do Vão, em planta (distância perpendicular dos
         dois nós do Vão à reta da aresta <= TOLERANCIA_GEOMETRICA); e
      2. DENTRO DA ALTURA da viga na cota: a cota da laje (topo, é o
         que o polígono representa) cai na faixa [topo - altura, topo]
         da viga -- a largura da viga não entra no teste.

    Aceita Vão inclinado e aresta inclinada: tanto a cota da laje
    quanto o topo da viga variam linearmente ao longo da aresta, então
    a diferença g(t) = z_laje(t) - z_topo_viga(t) também é linear, e o
    trecho apoiado é o intervalo em que g(t) está dentro da faixa de
    altura (resolvido em forma fechada, sem amostragem). Por isso o
    apoio pode sair PARCIAL mesmo com planta perfeitamente alinhada.

    Retorna (dist_ini, dist_fim): trecho da aresta apoiado no Vão, em
    distância 3D a partir de aresta_inicial (mesma convenção de
    Viga.restricoes). None se não há apoio (ou se o contato se reduz a
    um ponto).

    ESCOPO: mesma premissa de detectar_intersecao_viga_viga -- viga sem
    rotação própria (altura sempre vertical, ao longo de Z global).
    """
    tol = TOLERANCIA_GEOMETRICA
    p, q = vao.no_inicial, vao.no_final

    # --- aresta em planta: origem A, vetor d = B - A ---
    ax, ay = aresta_inicial.x, aresta_inicial.y
    dx, dy = aresta_final.x - ax, aresta_final.y - ay
    comprimento_planta = math.hypot(dx, dy)

    # aresta ou Vão sem extensão em planta (vertical): não há o que alinhar
    if comprimento_planta <= tol or math.hypot(q.x - p.x, q.y - p.y) <= tol:
        return None

    # --- (1) colinearidade em planta ---
    # produto vetorial com o versor da aresta = distância perpendicular do ponto à reta
    ux, uy = dx / comprimento_planta, dy / comprimento_planta
    for no in (p, q):
        if abs((no.x - ax) * uy - (no.y - ay) * ux) > tol:
            return None

    # --- (2) sobreposição em planta ---
    # t = posição normalizada ao longo da aresta (0 em aresta_inicial, 1 em aresta_final)
    def parametro(no: Ponto) -> float:
        return ((no.x - ax) * dx + (no.y - ay) * dy) / comprimento_planta**2

    t_p, t_q = parametro(p), parametro(q)
    t_min = max(0.0, min(t_p, t_q))  # início do trecho comum
    t_max = min(1.0, max(t_p, t_q))  # fim do trecho comum
    if t_max <= t_min:
        return None  # sem sobreposição (no máximo se tocam num ponto)

    # --- (3) faixa de altura: g(t) = g0 + g1 * t ---
    # topo da viga na cota da aresta: interpola o Vão pelo mesmo t (Vão colinear, então
    # o parâmetro do Vão é função linear de t)
    w0 = (0.0 - t_p) / (t_q - t_p)  # parâmetro do Vão sobre t = 0
    w1 = (1.0 - t_p) / (t_q - t_p)  # parâmetro do Vão sobre t = 1
    z_viga_t0 = p.z + w0 * (q.z - p.z)
    z_viga_t1 = p.z + w1 * (q.z - p.z)
    g0 = aresta_inicial.z - z_viga_t0
    g1 = (aresta_final.z - z_viga_t1) - g0

    # faixa permitida de g: altura_min (<= 0) .. altura_max (= 0), já com o TOPO como referência
    _, _, altura_min, altura_max = extensoes_do_perfil(vao.secao, referencia_topo=True)
    g_min, g_max = altura_min - tol, altura_max + tol

    if abs(g1) < _EPS_DECLIVIDADE:
        # diferença de cota constante: ou o trecho comum inteiro está na faixa, ou nenhum
        if not (g_min <= g0 <= g_max):
            return None
    else:
        # resolve g_min <= g0 + g1*t <= g_max para t (a ordem depende do sinal de g1)
        t_a = (g_min - g0) / g1
        t_b = (g_max - g0) / g1
        t_min = max(t_min, min(t_a, t_b))
        t_max = min(t_max, max(t_a, t_b))

    # --- converte t (planta) para distância 3D ao longo da aresta ---
    # t é proporcional à distância 3D (aresta reta), então basta escalar pelo comprimento real
    comprimento_3d = math.dist(
        (aresta_inicial.x, aresta_inicial.y, aresta_inicial.z),
        (aresta_final.x, aresta_final.y, aresta_final.z),
    )
    if (t_max - t_min) * comprimento_3d <= tol:
        return None  # contato reduzido a um ponto

    return t_min * comprimento_3d, t_max * comprimento_3d
