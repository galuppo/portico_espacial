from typing import List, Tuple, Dict, Optional

import numpy as np
import bisect

Ponto3D = Tuple[float, float, float]
Ponto2D = Tuple[float, float]
Barra3D = Tuple[Ponto3D, Ponto3D]


class Grelha:
	"""
	Gera uma malha ortogonal de pontos e barras internos a uma poligonal planar
	definida no espaço 3D.

	A poligonal deve ser planar (todos os pontos sobre um único plano, dentro de
	uma tolerância). A direção do eixo local e1 (direção "X" da malha) deve ser
	informada explicitamente, pois a orientação da base local não pode ser inferida
	de forma não ambígua a partir da poligonal isoladamente (dependeria da ordem
	dos vértices de entrada).

	- e1: normalizado a partir da projeção de `direcao_e1` sobre o plano da poligonal.
	- normal: calculada pelo método de Newell (robusto a poligonais com vértices
	  quase colineares no início da lista).
	- e2 = normal × e1 (ortonormal, completa a base local do plano).

	- As barras sempre vão de aresta a aresta da poligonal (um único elemento,
	  não segmentado nos cruzamentos internos da malha).
	- Os pontos gerados incluem os cruzamentos de borda (extremidades das barras)
	  e os cruzamentos internos da malha, todos contidos em alguma barra.
	"""

	_TOL = 1e-6               # tolerância para deduplicação de pontos no plano local
	_TOL_PLANARIDADE = 1e-6   # tolerância (distância) para aceitar a poligonal como planar
	_TOL_ANGULO_MINIMO_GRAUS = 0.5  # ângulo mínimo aceitável entre direcao_e1 e o plano
	_CASAS_DECIMAIS = 6  # compatível com _TOL (1e-6 ~ 6 casas decimais)

	def __init__(self, poligono: List[Ponto3D], direcao_e1: Ponto3D):
		if len(poligono) < 3:
			raise ValueError("A poligonal deve ter ao menos 3 vértices.")

		self.poligono: List[Ponto3D] = list(poligono)
		self._pontos_np = np.array(self.poligono, dtype=float)  # shape (n, 3)

		self._origem_plano = self._pontos_np[0]
		self._normal = self._calcular_normal_newell()
		self._verificar_planaridade()
		self._e1, self._e2 = self._construir_base_local(np.array(direcao_e1, dtype=float))

		self._poligono_local: np.ndarray = self._para_local(self._pontos_np)  # shape (n, 2)

		self._pontos: List[Ponto3D] = []
		self._pontos_locais: List[Ponto2D] = []
		self._barras_x: List[Barra3D] = []
		self._barras_y: List[Barra3D] = []
		self._espacamento_x_atual: float = -1
		self._espacamento_y_atual: float = -1
		self._coeficientes: Dict[Tuple[int, int], float] = {}   # chave (u,v) -> coeficiente
		self._coeficientes_lista: List[float] = []              # alinhada com self._pontos

	# ------------------------------------------------------------------
	# Geração
	# ------------------------------------------------------------------

	def gerar_grelha(
		self,
		espacamento_x: float,
		espacamento_y: float,
		origem: Optional[Ponto3D] = None,
	) -> None:
		"""
		Gera os pontos e as barras da grelha com o espaçamento informado.
		Toda chamada substitui a grelha gerada anteriormente.

		Parâmetros
		----------
		espacamento_x : espaçamento das linhas na direção do eixo local e1.
		espacamento_y : espaçamento das linhas na direção do eixo local e2.
		origem : ponto de referência (coordenadas globais) para travar a malha.
				 Não precisa estar sobre o plano: apenas sua projeção no plano
				 local é usada. Se None, usa o primeiro vértice da poligonal.
		"""
		if espacamento_x <= 0 or espacamento_y <= 0:
			raise ValueError("Os espaçamentos devem ser positivos.")

		origem_local = (
			tuple(self._para_local(np.array(origem, dtype=float)))
			if origem is not None
			else (0.0, 0.0)
		)

		linhas_u, linhas_v = self._linhas_da_malha(espacamento_x, espacamento_y, origem_local)

		pontos_unicos: Dict[Tuple[int, int], Ponto2D] = {}
		barras_u: List[Tuple[Ponto2D, Ponto2D]] = []
		barras_v: List[Tuple[Ponto2D, Ponto2D]] = []

		def registrar(p: Ponto2D) -> Ponto2D:
			p = (round(p[0], self._CASAS_DECIMAIS), round(p[1], self._CASAS_DECIMAIS))
			chave = self._chave(p)
			if chave not in pontos_unicos:
				pontos_unicos[chave] = p
			return pontos_unicos[chave]

		# --- barras na direção e2 (linhas verticais no plano local, u constante) ---
		for u in linhas_u:
			cruzamentos = self._intersecoes_verticais(u)
			for k in range(0, len(cruzamentos) - 1, 2):
				v_ini, v_fim = cruzamentos[k], cruzamentos[k + 1]
				p_ini = registrar((u, v_ini))
				p_fim = registrar((u, v_fim))
				barras_v.append((p_ini, p_fim))

				for v in linhas_v:
					if v_ini < v < v_fim:
						registrar((u, v))

		# --- barras na direção e1 (linhas horizontais no plano local, v constante) ---
		for v in linhas_v:
			cruzamentos = self._intersecoes_horizontais(v)
			for k in range(0, len(cruzamentos) - 1, 2):
				u_ini, u_fim = cruzamentos[k], cruzamentos[k + 1]
				p_ini = registrar((u_ini, v))
				p_fim = registrar((u_fim, v))
				barras_u.append((p_ini, p_fim))

				for u in linhas_u:
					if u_ini < u < u_fim:
						registrar((u, v))
		self._pontos_locais = list(pontos_unicos.values())
		self._pontos = [self._para_global(p) for p in pontos_unicos.values()]
		self._barras_x = [(self._para_global(a), self._para_global(b)) for a, b in barras_u]
		self._barras_y = [(self._para_global(a), self._para_global(b)) for a, b in barras_v]
		self._espacamento_x_atual = espacamento_x
		self._espacamento_y_atual = espacamento_y
		self._calcular_coeficientes_carga()  # NOVO: pré-computa tudo de uma vez

	# ------------------------------------------------------------------
	# Consultas
	# ------------------------------------------------------------------

	def pontos(self) -> List[Ponto3D]:
		"""Retorna os pontos da grelha gerada, em coordenadas globais (x, y, z)."""
		return list(self._pontos)

	def barras(self) -> List[Barra3D]:
		"""Retorna todas as barras da grelha (direção X local + direção Y local)."""
		return self._barras_x + self._barras_y

	def barras_x(self) -> List[Barra3D]:
		"""Barras orientadas na direção local e1 (v constante ao longo da barra)."""
		return list(self._barras_x)

	def barras_y(self) -> List[Barra3D]:
		"""Barras orientadas na direção local e2 (u constante ao longo da barra)."""
		return list(self._barras_y)

	@property
	def quantidade_pontos(self) -> int:
		return len(self._pontos)

	@property
	def quantidade_barras(self) -> int:
		return len(self._barras_x) + len(self._barras_y)

	def coeficiente_carga(self, ponto: Ponto3D) -> float:
		"""
		Retorna o coeficiente de carga (área de influência, regra do ponto médio)
		de um ponto da grelha. Consulta O(1) sobre valores pré-computados em
		gerar_grelha().

		Levanta ValueError se a grelha ainda não foi gerada, ou se o ponto
		informado não pertencer à grelha atual (verificação por proximidade,
		tolerância _TOL).
		"""
		if not self._pontos:
			raise ValueError("A grelha ainda não foi gerada. Chame gerar_grelha() antes.")

		ponto_local = tuple(self._para_local(np.array(ponto, dtype=float)))
		chave = self._chave(ponto_local)

		if chave not in self._coeficientes:
			raise ValueError(
				f"O ponto {ponto} não pertence à grelha gerada (tolerância: {self._TOL})."
			)

		return self._coeficientes[chave]

	def coeficientes_carga(self) -> List[float]:
		"""
		Retorna os coeficientes de carga (área de influência) de todos os pontos
		da grelha, na mesma ordem retornada por pontos().
		"""
		return list(self._coeficientes_lista)

	# ------------------------------------------------------------------
	# Base local do plano e transformações
	# ------------------------------------------------------------------

	def _calcular_normal_newell(self) -> np.ndarray:
		"""
		Calcula a normal do plano pelo método de Newell: robusto mesmo quando
		os primeiros vértices da poligonal estão quase colineares.
		"""
		n = len(self._pontos_np)
		normal = np.zeros(3)
		for i in range(n):
			atual = self._pontos_np[i]
			proximo = self._pontos_np[(i + 1) % n]
			normal[0] += (atual[1] - proximo[1]) * (atual[2] + proximo[2])
			normal[1] += (atual[2] - proximo[2]) * (atual[0] + proximo[0])
			normal[2] += (atual[0] - proximo[0]) * (atual[1] + proximo[1])

		norma = np.linalg.norm(normal)
		if norma < 1e-12:
			raise ValueError("Poligonal degenerada: não foi possível determinar um plano (normal nula).")
		return normal / norma

	def _construir_base_local(self, direcao_e1: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
		"""
		Projeta `direcao_e1` sobre o plano e normaliza para obter e1.
		e2 = normal × e1 completa a base ortonormal.

		Rejeita direcao_e1 se o ângulo entre ela e o plano for menor que
		`_TOL_ANGULO_MINIMO_GRAUS` (ou seja, se estiver quase paralela à normal).
		"""
		norma_direcao = np.linalg.norm(direcao_e1)
		if norma_direcao < 1e-12:
			raise ValueError("direcao_e1 não pode ser um vetor nulo.")

		# ângulo entre direcao_e1 e a normal (0° = paralela à normal, 90° = perpendicular à normal)
		cos_angulo_normal = np.clip(
			abs(np.dot(direcao_e1, self._normal)) / norma_direcao, -1.0, 1.0
		)
		angulo_com_normal = np.degrees(np.arccos(cos_angulo_normal))

		# ângulo entre direcao_e1 e o plano (0° = contida no plano, 90° = paralela à normal)
		angulo_com_plano = 90.0 - angulo_com_normal

		if angulo_com_plano > 90.0 - self._TOL_ANGULO_MINIMO_GRAUS:
			raise ValueError(
				f"direcao_e1 forma um ângulo de apenas {angulo_com_normal:.4f}° com a normal "
				f"do plano da poligonal (mínimo exigido: {self._TOL_ANGULO_MINIMO_GRAUS}°) — está "
				"praticamente alinhada com a normal do plano, então sua projeção sobre "
				"o plano é numericamente instável. Escolha uma direcao_e1 mais próxima "
				"de estar contida no plano da poligonal."
			)

		# projeção de direcao_e1 sobre o plano (remove a componente ao longo da normal)
		componente_normal = np.dot(direcao_e1, self._normal)
		e1_bruto = direcao_e1 - componente_normal * self._normal
		e1 = e1_bruto / np.linalg.norm(e1_bruto)
		e2 = np.cross(self._normal, e1)  # já normalizado: normal e e1 são ortonormais

		return e1, e2

	def _verificar_planaridade(self) -> None:
		distancias = np.abs((self._pontos_np - self._origem_plano) @ self._normal)
		idx_max = int(np.argmax(distancias))
		if distancias[idx_max] > self._TOL_PLANARIDADE:
			raise ValueError(
				"A poligonal não é planar: o vértice "
				f"{tuple(self._pontos_np[idx_max])} está a {distancias[idx_max]:.6g} "
				f"de distância do plano ajustado (tolerância: {self._TOL_PLANARIDADE})."
			)

	def _para_local(self, p: np.ndarray) -> np.ndarray:
		"""Converte ponto(s) global(is) para coordenadas locais (u, v). Aceita shape (3,) ou (n, 3)."""
		vetor = p - self._origem_plano
		u = vetor @ self._e1
		v = vetor @ self._e2
		coordenadas = np.stack([u, v], axis=-1)
		return np.round(coordenadas, self._CASAS_DECIMAIS)  # NOVO: elimina ruído de ponto flutuante

	def _para_global(self, p: Ponto2D) -> Ponto3D:
		u, v = p
		ponto_global = self._origem_plano + u * self._e1 + v * self._e2
		return (float(ponto_global[0]),
				float(ponto_global[1]),
		  		float(ponto_global[2]))

	# ------------------------------------------------------------------
	# Métodos internos (geometria 2D no plano local)
	# ------------------------------------------------------------------

	def _chave(self, p: Ponto2D) -> Tuple[int, int]:
		return (round(p[0] / self._TOL), round(p[1] / self._TOL))

	def _linhas_da_malha(
		self, espacamento_x: float, espacamento_y: float, origem_local: Ponto2D
	) -> Tuple[List[float], List[float]]:
		us = self._poligono_local[:, 0]
		vs = self._poligono_local[:, 1]
		u_min, u_max = float(us.min()), float(us.max())
		v_min, v_max = float(vs.min()), float(vs.max())
		u0, v0 = origem_local

		u_ini = u0 + espacamento_x * ((u_min - u0) // espacamento_x + 1)
		v_ini = v0 + espacamento_y * ((v_min - v0) // espacamento_y + 1)

		linhas_u, u = [], u_ini
		while u <= u_max:
			linhas_u.append(u)
			u += espacamento_x

		linhas_v, v = [], v_ini
		while v <= v_max:
			linhas_v.append(v)
			v += espacamento_y

		return linhas_u, linhas_v

	def _intersecoes_verticais(self, u: float) -> List[float]:
		vs = []
		n = len(self._poligono_local)
		for i in range(n):
			u1, v1 = self._poligono_local[i]
			u2, v2 = self._poligono_local[(i + 1) % n]
			if u1 == u2:
				continue  # aresta colinear com a malha (caso degenerado, ignorado)
			if (u1 <= u < u2) or (u2 <= u < u1):
				t = (u - u1) / (u2 - u1)
				vs.append(v1 + t * (v2 - v1))
		return sorted(vs)

	def _intersecoes_horizontais(self, v: float) -> List[float]:
		us = []
		n = len(self._poligono_local)
		for i in range(n):
			u1, v1 = self._poligono_local[i]
			u2, v2 = self._poligono_local[(i + 1) % n]
			if v1 == v2:
				continue
			if (v1 <= v < v2) or (v2 <= v < v1):
				t = (v - v1) / (v2 - v1)
				us.append(u1 + t * (u2 - u1))
		return sorted(us)

	# ------------------------------------------------------------------
	# Pré-cálculo dos coeficientes de carga
	# ------------------------------------------------------------------

	def _chave_escalar(self, valor: float) -> int:
		return round(valor / self._TOL)

	def _calcular_coeficientes_carga(self) -> None:
		"""
		Pré-computa, para todos os pontos da grelha gerada, o coeficiente de
		carga (área de influência, regra do ponto médio) e armazena em
		self._coeficientes (por chave) e self._coeficientes_lista (alinhada
		com self._pontos). Custo O(n log n) total.
		"""
		# agrupa pontos por linha: fixando v -> lista de u; fixando u -> lista de v
		grupos_por_v: Dict[int, List[float]] = {}
		grupos_por_u: Dict[int, List[float]] = {}

		for u, v in self._pontos_locais:
			grupos_por_v.setdefault(self._chave_escalar(v), []).append(u)
			grupos_por_u.setdefault(self._chave_escalar(u), []).append(v)

		for lista in grupos_por_v.values():
			lista.sort()
		for lista in grupos_por_u.values():
			lista.sort()

		self._coeficientes = {}
		self._coeficientes_lista = []

		for u, v in self._pontos_locais:
			lista_u = grupos_por_v[self._chave_escalar(v)]
			lista_v = grupos_por_u[self._chave_escalar(u)]

			comprimento_u = self._comprimento_tributario_lista(
				lista_u, u, self._espacamento_x_atual
			)
			comprimento_v = self._comprimento_tributario_lista(
				lista_v, v, self._espacamento_y_atual
			)

			coeficiente = comprimento_u * comprimento_v
			chave = self._chave((u, v))
			self._coeficientes[chave] = coeficiente
			self._coeficientes_lista.append(coeficiente)

	def _comprimento_tributario_lista(
		self, valores_ordenados: List[float], valor: float, espacamento_nominal: float
	) -> float:
		"""
		Comprimento tributário (regra do ponto médio) de `valor` dentro de
		`valores_ordenados` (já ordenada, valores de uma mesma linha da malha).
		Usa busca binária (bisect) para achar o índice de `valor`.
		"""
		if len(valores_ordenados) <= 1:
			# nenhuma barra perpendicular passa pelo ponto nesta direção
			return espacamento_nominal / 2.0

		idx = bisect.bisect_left(valores_ordenados, valor)
		# bisect_left pode "errar por 1" por causa de arredondamento de ponto
		# flutuante; corrige olhando o vizinho mais próximo, se necessário
		if idx == len(valores_ordenados) or (
			idx > 0 and abs(valores_ordenados[idx - 1] - valor) < abs(valores_ordenados[idx] - valor)
		):
			idx -= 1

		if idx == 0:
			return (valores_ordenados[idx + 1] - valores_ordenados[idx]) / 2.0
		elif idx == len(valores_ordenados) - 1:
			return (valores_ordenados[idx] - valores_ordenados[idx - 1]) / 2.0
		else:
			return (valores_ordenados[idx + 1] - valores_ordenados[idx - 1]) / 2.0



if __name__ == "__main__":
	# Exemplo 1: poligonal horizontal (z constante), e1 forçado no eixo global X
	poligonal_horizontal = [
		(0.0, 0.0, 3.0),
		(10.0, 0.0, 3.0),
		(10.0, 5.0, 3.0),
		(5.0, 5.0, 3.0),
		(5.0, 10.0, 3.0),
		(0.0, 10.0, 3.0),
	]
	grelha = Grelha(poligonal_horizontal, direcao_e1=(1.0, 0.0, 0.0))
	grelha.gerar_grelha(espacamento_x=0.25, espacamento_y=0.25)
	print(f"[Horizontal] Pontos: {grelha.quantidade_pontos}, Barras: {grelha.quantidade_barras}")
	for p in grelha.pontos():
		print(p)
		print(f"Coeficiente de carga de {p}: {grelha.coeficiente_carga(p):.4f}")

	# todos de uma vez, já alinhados com pontos()
	coefs = grelha.coeficientes_carga()
	soma = sum(coefs)
	print(f"Soma dos coeficientes: {soma:.4f}") # deve se aproximar da área do polígono

	# Exemplo 2: poligonal inclinada (plano oblíquo, ex.: laje de rampa)
	# direcao_e1 pode ser qualquer vetor não paralelo à normal -- aqui uso a direção
	# da própria rampa (primeira aresta) só para ilustrar; poderia ser (1, 0, 0) também,
	# desde que não seja paralela à normal do plano inclinado.
	poligonal_inclinada = [
		(0.0, 0.0, 0.0),
		(10.0, 0.0, 2.0),
		(10.0, 5.0, 2.0),
		(0.0, 5.0, 0.0),
	]
	grelha_inclinada = Grelha(poligonal_inclinada, direcao_e1=(1.0, 0.0, 0.0))
	grelha_inclinada.gerar_grelha(espacamento_x=.1, espacamento_y=.1)
	print(f"[Inclinada] Pontos: {grelha_inclinada.quantidade_pontos}, Barras: {grelha_inclinada.quantidade_barras}")
	for p in grelha_inclinada.pontos():
		print(p)
		print(f"Coeficiente de carga de {p}: {grelha_inclinada.coeficiente_carga(p):.4f}")
	# todos de uma vez, já alinhados com pontos()
	coefs = grelha_inclinada.coeficientes_carga()
	soma = sum(coefs)
	print(f"Soma dos coeficientes: {soma:.4f}") # deve se aproximar da área do polígono
	try:
		grelha_inclinada.coeficiente_carga((999.0, 999.0, 3.0))
	except ValueError as e:
		print(e)