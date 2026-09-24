"""
Módulo de propriedades do concreto (NBR 6118), trazido e adaptado do
arquivo original do usuário.

Concreto agora herda de Material -- pode ser usado diretamente em
qualquer Barra/Pilar/Viga/Laje do modelo (material=Concreto(...)), sem
precisar de nenhuma conversão. O tipo de agregado é exigido no
construtor (não em cada chamada de Eci_MPa/Ecs_MPa como no arquivo
original) -- assim o módulo de elasticidade já fica resolvido
internamente, sem parâmetro toda vez que for consultado.
"""

from enum import IntEnum
import math

from .materiais import Material


class TipoCimento(IntEnum):
    CP_I = 1
    CP_II = 2
    CP_III = 3
    CP_IV = 4
    CP_V_ARI = 5


class TipoAgregado(IntEnum):
    BASALTO_DIABASIO = 1
    GRANITO_GNAISSE = 2
    CALCARIO = 3
    ARENITO = 4


class Concreto(Material):
    """
    Propriedades do concreto (NBR 6118) -- é um Material completo
    (nome, modulo_elasticidade, coeficiente_poisson, peso_especifico
    herdados/preenchidos automaticamente a partir de fck e agregado).

    modulo_elasticidade usa o módulo secante (Ecs_MPa); coeficiente_poisson
    e peso_especifico vêm de `poisson` e `densidade_kNM3` abaixo.
    """

    def __init__(self, fck_MPa: float, agregado: TipoAgregado, nome: str):
        self._fck = fck_MPa
        self.agregado = agregado
        super().__init__(
            nome=nome,
            modulo_elasticidade=self.Ecs_MPa,
            coeficiente_poisson=self.poisson,
            peso_especifico=self.densidade_kNM3,
        )

    @property
    def fck_MPa(self) -> float:
        return self._fck

    @property
    def gamma_c(self) -> float:
        return 1.4

    @property
    def fcd_MPa(self) -> float:
        return self.fck_MPa / self.gamma_c

    @property
    def densidade_kNM3(self) -> float:
        return 25.0

    @property
    def alfa_termico(self) -> float:
        return 1.0e-5

    @property
    def fctm_MPa(self) -> float:
        if self.fck_MPa <= 50:
            return 0.30 * self.fck_MPa ** (2 / 3)
        else:
            return 2.12 * math.log(1 + 0.11 * self.fck_MPa)

    @property
    def fctk_inf_MPa(self) -> float:
        return 0.7 * self.fctm_MPa

    @property
    def poisson(self) -> float:
        return 0.2

    @property
    def fctk_sup_MPa(self) -> float:
        return 1.3 * self.fctm_MPa

    def fcj_MPa(self, j: int, cimento: TipoCimento) -> float:
        s = 0
        match cimento:
            case TipoCimento.CP_I: s = 0.25
            case TipoCimento.CP_II: s = 0.25
            case TipoCimento.CP_III: s = 0.38
            case TipoCimento.CP_IV: s = 0.38
            case TipoCimento.CP_V_ARI: s = 0.2
            case _: raise ValueError("Tipo de cimento não reconhecido.")

        betha1 = math.exp(s * (1 - (28 / j) ** 0.5))

        return self.fck_MPa * betha1

    @property
    def Eci_MPa(self) -> float:
        """Módulo de elasticidade tangente inicial -- usa self.agregado (não recebe mais parâmetro)."""
        match self.agregado:
            case TipoAgregado.BASALTO_DIABASIO: alfaE = 1.2
            case TipoAgregado.GRANITO_GNAISSE: alfaE = 1.0
            case TipoAgregado.CALCARIO: alfaE = 0.9
            case TipoAgregado.ARENITO: alfaE = 0.7
            case _: raise ValueError("Tipo de agregado não reconhecido.")

        if self.fck_MPa < 50:
            return alfaE * 5600.0 * math.sqrt(self.fck_MPa)
        else:
            return 21500.0 * alfaE * (self.fck_MPa / 10 + 1.25) ** (1 / 3)

    @property
    def Ecs_MPa(self) -> float:
        """Módulo de elasticidade secante -- usa self.agregado (não recebe mais parâmetro)."""
        alfa_i = min(0.8 + 0.2 * self.fck_MPa / 80.0, 1.0)
        return alfa_i * self.Eci_MPa
