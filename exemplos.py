"""
Exemplos de uso do Pórtico Espacial.

Refletem o estado ATUAL do pacote: constroem o modelo até o ponto de
chamar ModeloPortico.montar() (ainda não implementado -- é o próximo
passo do projeto). Servem pra validar que a API de construção do
modelo (via os métodos criar_* do ModeloPortico) faz sentido no uso
real.

id é sempre gerado internamente pelo ModeloPortico -- nunca informado
aqui. nome é informado explicitamente só quando queremos um valor
específico; nos outros casos, deixamos o próprio modelo gerar.
"""

from .elementos import ApoioRestricao
from .estrutura import ModeloPortico
from .geometria import Ponto
from .materiais import Material
from .secoes import SecaoRetangular
from .vinculos import Restricao


def exemplo_portico_simples() -> ModeloPortico:
    """
    Pórtico simples: dois pilares (Térreo -> Pav1) sustentando uma
    viga no nível do Pav1, com fundação (engaste, não modelada em
    detalhe) na base de cada pilar.

        P1 (0,0)         P2 (5,0)
         |                 |
         |----- V1 --------|   <- nível Pav1 (z = 3.0)
         |                 |
        (engaste)         (engaste)   <- nível Terreo (z = 0.0)
    """
    modelo = ModeloPortico()

    # 1) Pavimentos -- sempre ANTES de qualquer elemento, criados pelo próprio modelo
    terreo = modelo.criar_pavimento(nome="Terreo", elevacao=0.0)
    pav1 = modelo.criar_pavimento(nome="Pav1", elevacao=3.0)

    # 2) Seção e material -- reaproveitados pelos dois pilares e pela viga
    sec_pilar = SecaoRetangular(largura=0.3, altura=0.5)
    sec_viga = SecaoRetangular(largura=0.2, altura=0.5)
    concreto = Material(
        nome="C30", modulo_elasticidade=26_000_000, coeficiente_poisson=0.2, peso_especifico=25.0
    )

    # 3) Pilares P1 (0,0) e P2 (5,0), os dois do Terreo ao Pav1 -- id e nome
    #    ("P1", "P2") gerados automaticamente pelo modelo
    p1 = modelo.criar_pilar(
        pavimento_base=terreo, x_base=0.0, y_base=0.0,
        pavimento_topo=pav1, x_topo=0.0, y_topo=0.0,
        secao=sec_pilar, material=concreto,
    )
    p2 = modelo.criar_pilar(
        pavimento_base=terreo, x_base=5.0, y_base=0.0,
        pavimento_topo=pav1, x_topo=5.0, y_topo=0.0,
        secao=sec_pilar, material=concreto,
    )
    # Fundação não modelada em detalhe -- engaste direto na base de cada pilar
    p1.apoio_base = ApoioRestricao(restricao=Restricao.engastado(p1.ponto_base))
    p2.apoio_base = ApoioRestricao(restricao=Restricao.engastado(p2.ponto_base))

    # 4) Viga ligando P1 a P2, com o topo da seção no nível do Pav1 (z = 3.0)
    #    -- nome gerado a partir do Pav1 (numeração por pavimento)
    v1 = modelo.criar_viga(
        ponto_inicial=Ponto(0.0, 0.0, 3.0),
        ponto_final=Ponto(5.0, 0.0, 3.0),
        secao=sec_viga, material=concreto,
        pavimentos=[pav1],
    )

    # 5) modelo.montar()  -- ainda não implementado; próximo passo do projeto
    return modelo


def exemplo_viga_isolada_com_4_apoios() -> ModeloPortico:
    """
    Viga isolada (nenhum Pilar no modelo), contínua sobre 4 apoios
    simples -- útil pra validar o comportamento de uma viga sem
    modelar o resto do pórtico em volta.

        |---- 3,0 m ----|---- 3,0 m ----|---- 3,0 m ----|
        ^                ^               ^                ^
      apoio 1          apoio 2         apoio 3          apoio 4
     (dist. 0,0)      (dist. 3,0)     (dist. 6,0)      (dist. 9,0)
    """
    modelo = ModeloPortico()

    # Mesmo isolada, precisa de ao menos 1 Pavimento registrado (pode ser fictício)
    pav = modelo.criar_pavimento(nome="Ficticio", elevacao=0.0)

    sec = SecaoRetangular(largura=0.2, altura=0.5)
    concreto = Material(
        nome="C30", modulo_elasticidade=26_000_000, coeficiente_poisson=0.2, peso_especifico=25.0
    )

    viga = modelo.criar_viga(
        ponto_inicial=Ponto(0.0, 0.0, 0.0),
        ponto_final=Ponto(9.0, 0.0, 0.0),
        secao=sec, material=concreto,
        pavimentos=[pav],
        restricoes=[
            (0.0, Restricao.apoio_simples(Ponto(0.0, 0.0, 0.0))),
            (3.0, Restricao.apoio_simples(Ponto(3.0, 0.0, 0.0))),
            (6.0, Restricao.apoio_simples(Ponto(6.0, 0.0, 0.0))),
            (9.0, Restricao.apoio_simples(Ponto(9.0, 0.0, 0.0))),
        ],
    )

    # modelo.montar()  -- ainda não implementado; próximo passo do projeto
    return modelo


def exemplo_portico_com_laje() -> ModeloPortico:
    """
    Um cômodo simples: 4 pilares nos cantos, 4 vigas formando um laço
    fechado ao redor, e uma Laje apoiada nesse laço -- contorno da
    Laje é literalmente a lista das 4 Vigas (nenhum trecho precisa de
    Bordo aqui, porque não há aresta livre).

        P4 (0,4) ---- V3 ---- P3 (6,4)
          |                      |
          V4                     V2
          |                      |
        P1 (0,0) ---- V1 ---- P2 (6,0)

    Todos no nível do Pav1 (z = 3.0); pilares do Terreo ao Pav1.
    """
    modelo = ModeloPortico()

    terreo = modelo.criar_pavimento(nome="Terreo", elevacao=0.0)
    pav1 = modelo.criar_pavimento(nome="Pav1", elevacao=3.0)

    sec_pilar = SecaoRetangular(largura=0.3, altura=0.3)
    sec_viga = SecaoRetangular(largura=0.2, altura=0.4)
    sec_laje = SecaoRetangular(largura=1.0, altura=0.12)  # "largura" não se aplica à laje; altura = espessura (12 cm)
    concreto = Material(
        nome="C30", modulo_elasticidade=26_000_000, coeficiente_poisson=0.2, peso_especifico=25.0
    )

    # 4 pilares nos cantos de um retângulo de 6,0 x 4,0 m
    cantos = [(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)]
    pilares = [
        modelo.criar_pilar(
            pavimento_base=terreo, x_base=x, y_base=y,
            pavimento_topo=pav1, x_topo=x, y_topo=y,
            secao=sec_pilar, material=concreto,
        )
        for x, y in cantos
    ]
    for pilar in pilares:
        pilar.apoio_base = ApoioRestricao(restricao=Restricao.engastado(pilar.ponto_base))

    # 4 vigas ligando os pilares em sequência, fechando o laço (P1->P2->P3->P4->P1)
    vigas = []
    for i in range(4):
        p_ini, p_fim = pilares[i], pilares[(i + 1) % 4]
        vigas.append(
            modelo.criar_viga(
                ponto_inicial=Ponto(p_ini.x_base, p_ini.y_base, 3.0),
                ponto_final=Ponto(p_fim.x_base, p_fim.y_base, 3.0),
                secao=sec_viga, material=concreto,
                pavimentos=[pav1],
            )
        )

    # Laje apoiada no laço das 4 vigas -- sem nenhum trecho de Bordo (contorno fechado só por vigas)
    laje = modelo.criar_laje(
        pavimento=pav1,
        secao=sec_laje,
        material=concreto,
        direcao_e1=(1.0, 0.0, 0.0),
        contorno=vigas,
        espacamento_x=0.5,
        espacamento_y=0.5,
    )

    # modelo.montar()  -- ainda não implementado; é o que efetivamente gera o grid da Laje
    return modelo


if __name__ == "__main__":
    m1 = exemplo_portico_simples()
    print(f"Pórtico simples: {len(m1.pilares)} pilares, {len(m1.vigas)} vigas, {len(m1.pavimentos)} pavimentos")
    print(f"  ids: {[p.id for p in m1.pilares]}, nomes: {[p.nome for p in m1.pilares]}")
    print(f"  viga id/nome: {m1.vigas[0].id} / {m1.vigas[0].nome}")

    m2 = exemplo_viga_isolada_com_4_apoios()
    print(f"Viga isolada: {len(m2.vigas)} viga(s), {len(m2.vigas[0].restricoes)} restrições")
    print(f"  viga id/nome: {m2.vigas[0].id} / {m2.vigas[0].nome}")

    m3 = exemplo_portico_com_laje()
    print(f"Pórtico com laje: {len(m3.pilares)} pilares, {len(m3.vigas)} vigas, {len(m3.lajes)} laje(s)")
    print(f"  laje id/nome: {m3.lajes[0].id} / {m3.lajes[0].nome}, contorno com {len(m3.lajes[0].contorno)} vigas")
