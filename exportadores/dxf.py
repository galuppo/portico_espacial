"""
Adaptador de exportação: traduz um ModeloPortico (já montado) para um
arquivo DXF 3D, para inspeção visual em qualquer CAD (AutoCAD,
BricsCAD, LibreCAD etc.) -- não para análise estrutural.

Esta é a ÚNICA parte do Pórtico Espacial que conhece o formato DXF /
a biblioteca ezdxf -- o modelo de domínio (Pilar, Viga, Laje, Barra)
não importa nada deste módulo, mesmo princípio do exportador SAP2000
(sap2000.py).

Convenções desta primeira versão (decisões de projeto, não normas --
ajustáveis se não corresponderem ao que você espera ver no CAD):

  - `exportar()` gera todas as Barras como LINE (linhas simples, sem
    volume). `exportar_solido()` gera cada Barra como um sólido
    extrudado pela seção real (MESH fechada -- 2 tampas + paredes
    laterais), usando `SecaoTransversal.vertices` (funciona com
    qualquer seção, retangular ou poligonal). ezdxf não cria
    `3DSOLID`/ACIS de verdade (isso exige o kernel do AutoCAD) -- MESH
    é o equivalente universal, abre como sólido fechado em qualquer
    CAD. Ambos os métodos aceitam o mesmo `pavimento` opcional e
    desenham apoios/rótulos do mesmo jeito (sempre como linhas/texto,
    mesmo no modo sólido).

  - Orientação da seção no espaço: como nenhuma outra parte do
    projeto ainda interpreta `Barra.rotacao` geometricamente, segui a
    convenção default de eixos locais do SAP2000 (mesma referência
    que este projeto já usa pra tudo o mais) -- eixo local 1 ao longo
    da barra (no_inicial -> no_final); eixo local 2 default = projeção
    de +Z global perpendicular ao eixo 1 (mantém a seção "em pé"), ou
    +X global se a barra for exatamente vertical; eixo local 3 =
    eixo1 × eixo2; `rotacao` (graus) gira 2/3 em torno de 1. A altura
    da seção (dimensão do eixo forte, `inercia_x`) fica alinhada ao
    eixo local 2; a largura (`inercia_y`), ao eixo local 3.

  - Layers organizadas por PAVIMENTO + TIPO (ex.: "PAV1-PILARES"),
    pra poder ligar/desligar cada combinação separadamente em
    qualquer visualizador de CAD.

  - Pavimento de cada elemento: Lance usa `Lance.pavimento` (campo
    explícito, já atribuído em `_montar_pilares` pela regra do
    "pé-direito duplo" -- é o pavimento do TOPO do trecho, não da
    base; um pilar Térreo->Pav1 sem quebra intermediária tem seu
    único Lance pertencendo ao Pav1, não ao Térreo -- só o apoio de
    base é que fica no Térreo); Laje (barras de grid + rótulo) usa
    `Laje.pavimento` (campo explícito, direto); os apoios de Pilar
    usam `Pilar.pavimento_base`/`pavimento_topo` (idem). Só o Vão não
    guarda pavimento próprio no modelo de domínio -- usa o pavimento,
    dentre os que a sua Viga efetivamente toca (`Viga.pavimentos`),
    com elevação mais próxima do z médio do vão; os apoios desse Vão
    (apoio_inicial/apoio_final) herdam o mesmo pavimento do vão.
    Restringir aos pavimentos da própria Viga (em vez de todos os do
    modelo) evita associar um vão a um pavimento que a viga nem toca,
    só por estar "mais perto" dele em z.

  - `exportar()` aceita um `pavimento: Pavimento | None` opcional --
    quando informado (o mesmo objeto retornado por
    `ModeloPortico.criar_pavimento`), só desenha barras/apoios/
    rótulos classificados naquele pavimento, pelas regras acima.
    `None` (padrão) exporta o modelo inteiro.

  - Rótulo (TEXT, id + nome) no ponto médio de cada Lance/Vão/Link.
    Pilar e Viga não recebem rótulo próprio (já cobertos pelos seus
    Lances/Vãos); Laje recebe um único rótulo no centróide do seu
    contorno, já que as barras de grid não têm nome individual.

  - Rótulos ficam sempre no plano XY (não giram junto com a barra) --
    mais simples de gerar e ainda legível em vista de topo; pode não
    ficar tão legível de frente para pilares/vigas muito inclinados.

  - Apoio real (Restricao, via ApoioRestricao em Pilar.apoio_base/
    apoio_topo e Vao.apoio_inicial/apoio_final) vira um símbolo de
    linhas na layer "{PAV}-APOIOS", com a forma indicando o tipo de
    restrição (ver _classificar_restricao): engastado (asterisco 3D
    nos 3 eixos), apoio simples/articulado (tripé invertido, símbolo
    clássico de apoio articulado), elástico (mola em zigue-zague) ou
    misto (cruz horizontal + haste vertical, quando os 6 graus não
    seguem nenhum dos padrões acima). ApoioElemento (apoio em outro
    Pilar/Viga do próprio modelo, não uma Restricao) não gera
    símbolo -- já fica implícito na geometria dos dois elementos se
    tocando.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import ezdxf

from ..elementos import ApoioRestricao, Laje, Pavimento, Vao, Viga
from ..estrutura import ModeloPortico
from ..geometria import Ponto
from ..vinculos import Restricao, TipoRestricao

# Caracteres não permitidos em nome de layer DXF -- sanitizados na hora de montar o nome.
_CARACTERES_INVALIDOS_LAYER = '<>/\\":;?*|=`'

Vetor3D = Tuple[float, float, float]


class ExportadorDxf:
    """Exporta um ModeloPortico montado para um arquivo DXF 3D de inspeção visual."""

    # Cores ACI (AutoCAD Color Index) por tipo de elemento -- fixas; só o
    # nome da layer varia conforme o pavimento.
    _COR_PILARES = 5  # azul
    _COR_VIGAS = 1  # vermelho
    _COR_LAJES = 3  # verde
    _COR_APOIOS = 2  # amarelo
    _COR_ROTULOS = 8  # cinza

    def __init__(self, altura_texto: float = 0.2, tamanho_apoio: float = 0.3):
        """
        altura_texto: altura (em unidades do modelo) do TEXT de cada rótulo de id/nome.
        tamanho_apoio: tamanho (em unidades do modelo) dos símbolos de apoio.
        """
        self.altura_texto = altura_texto
        self.tamanho_apoio = tamanho_apoio
        self._doc = None  # atribuídos em exportar(); guardados aqui só
        self._layers_criadas: set[str] = set()  # pra evitar recriar a mesma layer

    def exportar(self, modelo: ModeloPortico, caminho: str, pavimento: Pavimento | None = None) -> None:
        """
        Gera o arquivo DXF em `caminho` a partir de um ModeloPortico já montado.
        Toda Barra vira uma LINE simples (sem volume).

        pavimento: se informado, restringe a exportação só aos elementos
        classificados naquele pavimento (ver regras de classificação na
        docstring do módulo). Deve ser um Pavimento do próprio `modelo`
        (o objeto retornado por `ModeloPortico.criar_pavimento`).
        """
        self._gerar(modelo, caminho, pavimento, solido=False)

    def exportar_solido(self, modelo: ModeloPortico, caminho: str, pavimento: Pavimento | None = None) -> None:
        """
        Igual a `exportar()`, mas cada Barra vira um sólido extrudado pela
        sua seção real (MESH fechada), em vez de uma linha -- ver a
        convenção de orientação da seção na docstring do módulo. Apoios e
        rótulos continuam sendo desenhados como linhas/texto, iguais aos
        de `exportar()`.
        """
        self._gerar(modelo, caminho, pavimento, solido=True)

    def _gerar(self, modelo: ModeloPortico, caminho: str, pavimento: Pavimento | None, solido: bool) -> None:
        if not modelo.pavimentos:
            raise ValueError("O modelo não tem nenhum Pavimento registrado.")
        if not modelo.pilares and not modelo.vigas and not modelo.lajes:
            raise ValueError("O modelo não tem nenhum Pilar, Viga ou Laje para exportar.")
        if pavimento is not None and pavimento not in modelo.pavimentos:
            raise ValueError(f"O pavimento informado ({pavimento.nome!r}) não pertence a este modelo.")

        self._doc = ezdxf.new("R2018", setup=True)
        self._layers_criadas = set()
        msp = self._doc.modelspace()
        algo_desenhado = False
        desenhar_barra = self._desenhar_solido if solido else self._desenhar_barra

        for pilar in modelo.pilares:
            for lance in pilar.lances:
                if pavimento is None or lance.pavimento == pavimento:
                    desenhar_barra(msp, lance, lance.pavimento, "PILARES", self._COR_PILARES)
                    algo_desenhado = True
            if (pavimento is None or pilar.pavimento_base == pavimento) and self._desenhar_apoio(
                msp, pilar.apoio_base, pilar.pavimento_base
            ):
                algo_desenhado = True
            if (pavimento is None or pilar.pavimento_topo == pavimento) and self._desenhar_apoio(
                msp, pilar.apoio_topo, pilar.pavimento_topo
            ):
                algo_desenhado = True

        for viga in modelo.vigas:
            for vao in viga.vaos:
                pavimento_vao = self._pavimento_do_vao(vao, viga, modelo.pavimentos)
                if pavimento is None or pavimento_vao == pavimento:
                    desenhar_barra(msp, vao, pavimento_vao, "VIGAS", self._COR_VIGAS)
                    self._desenhar_apoio(msp, vao.apoio_inicial, pavimento_vao)
                    self._desenhar_apoio(msp, vao.apoio_final, pavimento_vao)
                    algo_desenhado = True

        for laje in modelo.lajes:
            if pavimento is None or laje.pavimento == pavimento:
                for barra in [*laje.barras_grid_x, *laje.barras_grid_y]:
                    desenhar_barra(msp, barra, laje.pavimento, "LAJES", self._COR_LAJES)
                self._desenhar_rotulo_laje(msp, laje, laje.pavimento)
                algo_desenhado = True

        if not algo_desenhado:
            raise ValueError(f"Nenhum elemento do modelo foi classificado no pavimento {pavimento.nome!r}.")

        self._doc.saveas(caminho)

    # ------------------------------------------------------------------
    # Barras + rótulos
    # ------------------------------------------------------------------

    def _desenhar_barra(self, msp, barra, pavimento: Pavimento, sufixo_layer: str, cor: int) -> None:
        """Desenha uma Barra (Lance/Vão/Link/barra de grid) como LINE 3D + rótulo de id/nome."""
        p1, p2 = barra.no_inicial, barra.no_final
        layer = self._layer(pavimento, sufixo_layer, cor)
        msp.add_line((p1.x, p1.y, p1.z), (p2.x, p2.y, p2.z), dxfattribs={"layer": layer})

        # Link (excentricidade) não tem 'nome' de documentação, só id -- os
        # demais (Lance, Vão) têm nome derivado do elemento pai (ex.: "P1.2").
        nome = getattr(barra, "nome", None)
        texto = f"{nome} [{barra.id}]" if nome else f"[{barra.id}]"
        self._desenhar_rotulo(msp, texto, self._ponto_medio(p1, p2), pavimento)

    def _desenhar_solido(self, msp, barra, pavimento: Pavimento, sufixo_layer: str, cor: int) -> None:
        """
        Desenha uma Barra como sólido extrudado (MESH fechada) pela sua
        seção real (`barra.secao.vertices`) + rótulo de id/nome, igual a
        `_desenhar_barra`. Ver orientação da seção na docstring do módulo.
        """
        no_i, no_f = barra.no_inicial, barra.no_final
        _, eixo2, eixo3 = self._eixos_locais(no_i, no_f, barra.rotacao)
        vertices_secao = self._vertices_anti_horario(barra.secao.vertices)
        n = len(vertices_secao)

        def ponto_3d(no: Ponto, vx: float, vy: float) -> Tuple[float, float, float]:
            dx, dy, dz = self._soma(self._escala(eixo3, vx), self._escala(eixo2, vy))
            return (no.x + dx, no.y + dy, no.z + dz)

        tampa_i = [ponto_3d(no_i, vx, vy) for vx, vy in vertices_secao]
        tampa_f = [ponto_3d(no_f, vx, vy) for vx, vy in vertices_secao]

        layer = self._layer(pavimento, sufixo_layer, cor)
        malha = msp.add_mesh(dxfattribs={"layer": layer})
        with malha.edit_data() as dados:
            dados.vertices = tampa_i + tampa_f
            # tampa em no_i (índices 0..n-1) e tampa em no_f (índices n..2n-1,
            # em ordem invertida -- vista de fora, cada tampa fica anti-horária,
            # já que as duas tampas "olham" em sentidos opostos ao longo do eixo 1)
            faces = [list(range(n)), [n + i for i in reversed(range(n))]]
            for i in range(n):
                j = (i + 1) % n
                faces.append([i, j, n + j, n + i])  # parede lateral da aresta i -> j
            dados.faces = faces

        nome = getattr(barra, "nome", None)
        texto = f"{nome} [{barra.id}]" if nome else f"[{barra.id}]"
        self._desenhar_rotulo(msp, texto, self._ponto_medio(no_i, no_f), pavimento)

    def _desenhar_rotulo_laje(self, msp, laje: Laje, pavimento: Pavimento) -> None:
        """Rótulo único da Laje (id + nome), no centróide simples do seu contorno."""
        assert laje.grelha is not None, "Laje.grelha só existe depois de ModeloPortico.montar()"
        pontos = laje.grelha.poligono
        centro = Ponto(
            x=sum(p[0] for p in pontos) / len(pontos),
            y=sum(p[1] for p in pontos) / len(pontos),
            z=sum(p[2] for p in pontos) / len(pontos),
        )
        self._desenhar_rotulo(msp, f"{laje.nome} [{laje.id}]", centro, pavimento)

    def _desenhar_rotulo(self, msp, texto: str, ponto: Ponto, pavimento: Pavimento) -> None:
        layer = self._layer(pavimento, "ROTULOS", self._COR_ROTULOS)
        entidade = msp.add_text(texto, dxfattribs={"layer": layer, "height": self.altura_texto})
        entidade.set_placement((ponto.x, ponto.y, ponto.z))

    # ------------------------------------------------------------------
    # Apoios
    # ------------------------------------------------------------------

    def _desenhar_apoio(self, msp, apoio, pavimento: Pavimento) -> bool:
        """Retorna True se desenhou algo (usado por exportar() pra saber se o filtro de pavimento achou algo)."""
        if not isinstance(apoio, ApoioRestricao):
            return False  # None ou ApoioElemento -- não vira símbolo (ver docstring do módulo)
        restricao = apoio.restricao
        layer = self._layer(pavimento, "APOIOS", self._COR_APOIOS)
        for extremo_a, extremo_b in self._segmentos_simbolo_apoio(restricao):
            msp.add_line(
                (extremo_a.x, extremo_a.y, extremo_a.z),
                (extremo_b.x, extremo_b.y, extremo_b.z),
                dxfattribs={"layer": layer},
            )
        return True

    @staticmethod
    def _classificar_restricao(restricao: Restricao) -> str:
        """Classifica os 6 graus de liberdade num dos 4 padrões visuais do símbolo de apoio."""
        graus = [
            restricao.translacao_x,
            restricao.translacao_y,
            restricao.translacao_z,
            restricao.rotacao_x,
            restricao.rotacao_y,
            restricao.rotacao_z,
        ]
        if any(g.tipo == TipoRestricao.ELASTICO for g in graus):
            return "ELASTICO"
        if all(g.tipo == TipoRestricao.RESTRINGIDO for g in graus):
            return "ENGASTADO"
        translacoes, rotacoes = graus[:3], graus[3:]
        todas_translacoes_restringidas = all(g.tipo == TipoRestricao.RESTRINGIDO for g in translacoes)
        todas_rotacoes_livres = all(g.tipo == TipoRestricao.LIVRE for g in rotacoes)
        if todas_translacoes_restringidas and todas_rotacoes_livres:
            return "SIMPLES"
        return "MISTO"

    def _segmentos_simbolo_apoio(self, restricao: Restricao) -> list[tuple[Ponto, Ponto]]:
        """
        Segmentos (pares de Ponto) do símbolo de linhas do apoio, centrado
        em restricao.no, com tamanho self.tamanho_apoio -- a forma indica
        o tipo de restrição (ver _classificar_restricao).
        """
        no = restricao.no
        tamanho = self.tamanho_apoio
        tipo = self._classificar_restricao(restricao)

        if tipo == "ENGASTADO":
            # asterisco 3D: uma haste em cada sentido dos 3 eixos locais globais
            eixos = [(tamanho, 0, 0), (0, tamanho, 0), (0, 0, tamanho)]
            return [
                (Ponto(no.x - dx, no.y - dy, no.z - dz), Ponto(no.x + dx, no.y + dy, no.z + dz))
                for dx, dy, dz in eixos
            ]

        if tipo == "SIMPLES":
            # tripé invertido (símbolo clássico de apoio articulado): 3 pernas
            # do nó até 3 pontos abaixo, espaçadas 120° em planta
            pernas = []
            for k in range(3):
                angulo = math.radians(120 * k)
                pe = Ponto(no.x + tamanho * math.cos(angulo), no.y + tamanho * math.sin(angulo), no.z - tamanho)
                pernas.append((no, pe))
            return pernas

        if tipo == "ELASTICO":
            # mola em zigue-zague na vertical, abaixo do nó
            n_dentes = 4
            largura = tamanho / 3
            segmentos = []
            anterior = no
            for i in range(n_dentes):
                sinal = 1 if i % 2 == 0 else -1
                proximo = Ponto(no.x + sinal * largura, no.y, no.z - tamanho * (i + 1) / n_dentes)
                segmentos.append((anterior, proximo))
                anterior = proximo
            segmentos.append((anterior, Ponto(no.x, no.y, no.z - tamanho)))
            return segmentos

        # MISTO: nenhum padrão comum reconhecido -- cruz horizontal + haste
        # vertical, só pra sinalizar "existe restrição aqui, conferir os graus
        # de liberdade individualmente" sem assumir um símbolo específico
        meio = tamanho / 2
        return [
            (Ponto(no.x - meio, no.y, no.z), Ponto(no.x + meio, no.y, no.z)),
            (Ponto(no.x, no.y - meio, no.z), Ponto(no.x, no.y + meio, no.z)),
            (no, Ponto(no.x, no.y, no.z - tamanho)),
        ]

    # ------------------------------------------------------------------
    # Auxiliares (pavimento, layer, geometria)
    # ------------------------------------------------------------------

    @staticmethod
    def _pavimento_do_vao(vao: Vao, viga: Viga, pavimentos_modelo: list[Pavimento]) -> Pavimento:
        """
        Vão não guarda pavimento próprio -- usa o pavimento, dentre os que
        a própria Viga toca (`viga.pavimentos`), com elevação mais próxima
        do z médio do vão. Só cai nos pavimentos do modelo inteiro se a
        Viga não tiver nenhum registrado (não deveria acontecer após
        `montar()`, mas evita um IndexError caso aconteça).
        """
        candidatos = viga.pavimentos or pavimentos_modelo
        z_medio = (vao.no_inicial.z + vao.no_final.z) / 2
        return min(candidatos, key=lambda p: abs(p.elevacao - z_medio))

    def _layer(self, pavimento: Pavimento, sufixo: str, cor: int) -> str:
        nome = f"{pavimento.nome}-{sufixo}".upper()
        for caractere in _CARACTERES_INVALIDOS_LAYER:
            nome = nome.replace(caractere, "_")
        if nome not in self._layers_criadas:
            self._doc.layers.add(nome, color=cor)
            self._layers_criadas.add(nome)
        return nome

    @staticmethod
    def _ponto_medio(p1: Ponto, p2: Ponto) -> Ponto:
        return Ponto((p1.x + p2.x) / 2, (p1.y + p2.y) / 2, (p1.z + p2.z) / 2)

    # ------------------------------------------------------------------
    # Geometria do sólido extrudado (eixos locais + vetores 3D)
    # ------------------------------------------------------------------

    def _eixos_locais(
        self, no_inicial: Ponto, no_final: Ponto, rotacao_graus: float
    ) -> Tuple[Vetor3D, Vetor3D, Vetor3D]:
        """
        Base ortonormal local da barra (eixo1, eixo2, eixo3), seguindo a
        convenção default de eixos locais do SAP2000: eixo1 ao longo da
        barra (no_inicial -> no_final); eixo2 default = projeção de +Z
        global perpendicular ao eixo1 (mantém a seção "em pé"), ou +X
        global se a barra for exatamente vertical; eixo3 = eixo1 × eixo2.
        `rotacao_graus` gira eixo2/eixo3 em torno do eixo1.
        """
        eixo1 = self._normalizar(self._subtrair((no_final.x, no_final.y, no_final.z), (no_inicial.x, no_inicial.y, no_inicial.z)))

        global_z = (0.0, 0.0, 1.0)
        paralelo_a_z = abs(self._produto_escalar(eixo1, global_z)) > 1 - 1e-9
        if paralelo_a_z:
            eixo2_default = (1.0, 0.0, 0.0)  # convenção SAP2000 p/ barra vertical: +X global
        else:
            projecao = self._subtrair(global_z, self._escala(eixo1, self._produto_escalar(eixo1, global_z)))
            eixo2_default = self._normalizar(projecao)

        eixo3_default = self._normalizar(self._produto_vetorial(eixo1, eixo2_default))

        angulo = math.radians(rotacao_graus)
        cos_a, sin_a = math.cos(angulo), math.sin(angulo)
        eixo2 = self._soma(self._escala(eixo2_default, cos_a), self._escala(eixo3_default, sin_a))
        eixo3 = self._soma(self._escala(eixo3_default, cos_a), self._escala(eixo2_default, -sin_a))

        return eixo1, eixo2, eixo3

    @staticmethod
    def _vertices_anti_horario(vertices: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Garante sentido anti-horário (área com sinal positiva) -- normais das faces da MESH saem pra fora."""
        area_dupla = sum(
            vertices[i][0] * vertices[(i + 1) % len(vertices)][1] - vertices[(i + 1) % len(vertices)][0] * vertices[i][1]
            for i in range(len(vertices))
        )
        return vertices if area_dupla > 0 else list(reversed(vertices))

    @staticmethod
    def _subtrair(a: Vetor3D, b: Vetor3D) -> Vetor3D:
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    @staticmethod
    def _soma(a: Vetor3D, b: Vetor3D) -> Vetor3D:
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    @staticmethod
    def _escala(v: Vetor3D, k: float) -> Vetor3D:
        return (v[0] * k, v[1] * k, v[2] * k)

    @staticmethod
    def _produto_escalar(a: Vetor3D, b: Vetor3D) -> float:
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    @staticmethod
    def _produto_vetorial(a: Vetor3D, b: Vetor3D) -> Vetor3D:
        return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

    @staticmethod
    def _normalizar(v: Vetor3D) -> Vetor3D:
        norma = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
        if norma < 1e-12:
            raise ValueError("Não é possível normalizar um vetor nulo (barra com no_inicial == no_final?).")
        return (v[0] / norma, v[1] / norma, v[2] / norma)
