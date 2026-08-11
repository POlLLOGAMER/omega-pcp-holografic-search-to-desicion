"""CNF -> R1CS -> LDE: prototipo algebraico de búsqueda SAT vía PCP.

La implementación es deliberadamente explícita y no utiliza Z3, SAT solvers ni
recursión. La parte que produce una prueba necesita un testigo para la instancia
candidata; en un PCP real ese testigo estaría codificado en una palabra de prueba
commitida y la consistencia se comprobaría mediante un esquema PCS.

Convención de índices:
    * x_1, ..., x_n son las variables booleanas de la CNF.
    * En el vector R1CS, la posición 0 contiene la constante 1.
    * Las posiciones 1..n contienen x_1..x_n.
    * Las posiciones posteriores son variables auxiliares de las cadenas de
      multiplicación de las cláusulas.

La codificación de una cláusula C = (l_1 v ... v l_k) usa

    prod_j (1 - l_j) = 0,

porque cada literal l_j vale 0/1. Cada producto se descompone en una cadena
R1CS de multiplicaciones binarias.

La LDE usa interpolación de Lagrange sobre un subgrupo multiplicativo de F_p.
Para una tabla base de m valores, se evalúa el polinomio de grado < m en un
subgrupo extendido de tamaño factor*m. El campo por defecto es
p = 2013265921 = 15*2^27 + 1, que proporciona dominios de tamaño potencia de 2
suficientes para ejemplos prácticos.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import argparse
import hashlib
import math
import random
import time


DEFAULT_P = 2_013_265_921


class PrimeField:
    """Aritmética exacta en el cuerpo primo F_p."""

    def __init__(self, p: int = DEFAULT_P) -> None:
        if p <= 2:
            raise ValueError("p debe ser un primo impar mayor que 2")
        if not self._is_prime(p):
            raise ValueError(f"p={p} no parece ser primo")
        self.p = p

    @staticmethod
    def _is_prime(n: int) -> bool:
        if n < 2:
            return False
        small_primes = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
        for q in small_primes:
            if n == q:
                return True
            if n % q == 0:
                return False
        d, s = n - 1, 0
        while d % 2 == 0:
            s += 1
            d //= 2
        # Bases deterministas para enteros de 32 bits; el campo por defecto cae
        # en este rango, y la rutina sigue siendo robusta para ejemplos mayores.
        bases = (2, 3, 5, 7, 11, 13, 17)
        for a in bases:
            if a >= n:
                continue
            x = pow(a, d, n)
            if x in (1, n - 1):
                continue
            for _ in range(s - 1):
                x = (x * x) % n
                if x == n - 1:
                    break
            else:
                return False
        return True

    def norm(self, a: int) -> int:
        return a % self.p

    def add(self, a: int, b: int) -> int:
        return (a + b) % self.p

    def sub(self, a: int, b: int) -> int:
        return (a - b) % self.p

    def mul(self, a: int, b: int) -> int:
        return (a * b) % self.p

    def neg(self, a: int) -> int:
        return (-a) % self.p

    def pow(self, a: int, e: int) -> int:
        if e < 0:
            return pow(self.inv(a), -e, self.p)
        return pow(a % self.p, e, self.p)

    def inv(self, a: int) -> int:
        a %= self.p
        if a == 0:
            raise ZeroDivisionError("0 no tiene inverso en F_p")
        return pow(a, self.p - 2, self.p)

    def div(self, a: int, b: int) -> int:
        return self.mul(a, self.inv(b))

    def factorize(self, n: int) -> Tuple[int, ...]:
        factors: List[int] = []
        d = 2
        while d * d <= n:
            if n % d == 0:
                factors.append(d)
                while n % d == 0:
                    n //= d
            d = 3 if d == 2 else d + 2
        if n > 1:
            factors.append(n)
        return tuple(factors)

    def primitive_root(self) -> int:
        phi = self.p - 1
        for g in range(2, self.p):
            if all(pow(g, phi // q, self.p) != 1 for q in self.factorize(phi)):
                return g
        raise RuntimeError("no se encontró una raíz primitiva")

    def root_of_unity(self, order: int) -> int:
        """Devuelve una raíz de orden exacto ``order`` en F_p^*."""
        if order <= 0 or (self.p - 1) % order != 0:
            raise ValueError(f"el orden {order} no divide p-1={self.p - 1}")
        g = self.primitive_root()
        omega = pow(g, (self.p - 1) // order, self.p)
        if order > 1 and pow(omega, order // 2, self.p) == 1:
            raise RuntimeError("la raíz encontrada no tiene el orden solicitado")
        return omega


@dataclass(frozen=True)
class CNF:
    """Fórmula CNF, con literales DIMACS: i significa x_i y -i significa ¬x_i."""

    num_vars: int
    clauses: Tuple[Tuple[int, ...], ...]
    fixed: Mapping[int, bool] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.num_vars < 0:
            raise ValueError("num_vars debe ser no negativo")
        normalized: List[Tuple[int, ...]] = []
        for clause in self.clauses:
            c = tuple(int(lit) for lit in clause)
            if any(lit == 0 or abs(lit) > self.num_vars for lit in c):
                raise ValueError("literal fuera del rango de variables")
            if len(set(c)) != len(c):
                raise ValueError("no se permiten literales repetidos dentro de una cláusula")
            if any(-lit in c for lit in c):
                # La cláusula es una tautología; la mantenemos porque su valor es
                # siempre verdadero, pero no la usamos como restricción R1CS.
                object.__setattr__(self, "clauses", tuple(self.clauses))
            normalized.append(c)
        for var, value in self.fixed.items():
            if not 1 <= int(var) <= self.num_vars:
                raise ValueError("variable fija fuera de rango")
            if not isinstance(value, bool):
                raise TypeError("los valores fijos deben ser bool")
        object.__setattr__(self, "clauses", tuple(normalized))
        object.__setattr__(self, "fixed", dict(self.fixed))

    @classmethod
    def from_clauses(
        cls, num_vars: int, clauses: Iterable[Iterable[int]]
    ) -> "CNF":
        return cls(num_vars, tuple(tuple(c) for c in clauses))

    @classmethod
    def from_dimacs(cls, text: str) -> "CNF":
        """Parsea una instancia DIMACS CNF sin depender de bibliotecas externas."""
        num_vars: Optional[int] = None
        clauses: List[Tuple[int, ...]] = []
        current: List[int] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("c"):
                continue
            parts = line.split()
            if parts[0] == "p":
                if len(parts) < 4 or parts[1].lower() != "cnf":
                    raise ValueError("cabecera DIMACS inválida")
                num_vars = int(parts[2])
                continue
            if num_vars is None:
                raise ValueError("falta la cabecera DIMACS")
            for token in parts:
                lit = int(token)
                if lit == 0:
                    clauses.append(tuple(current))
                    current.clear()
                else:
                    current.append(lit)
        if current:
            raise ValueError("la última cláusula DIMACS no termina en 0")
        if num_vars is None:
            raise ValueError("falta la cabecera DIMACS")
        return cls(num_vars, tuple(clauses))

    def evaluate(self, assignment: Mapping[int, bool]) -> bool:
        values = dict(self.fixed)
        values.update({int(k): bool(v) for k, v in assignment.items()})
        for clause in self.clauses:
            satisfied = False
            for lit in clause:
                value = values.get(abs(lit))
                if value is None:
                    raise ValueError(f"falta el valor de x_{abs(lit)}")
                if value if lit > 0 else not value:
                    satisfied = True
                    break
            if not satisfied:
                return False
        return True

    def restrict(self, variable: int, value: bool) -> "CNF":
        """Sustituye x_variable por una constante y simplifica la CNF."""
        variable = int(variable)
        if not 1 <= variable <= self.num_vars:
            raise ValueError("variable fuera de rango")
        new_fixed = dict(self.fixed)
        old = new_fixed.get(variable)
        if old is not None and old != value:
            # La sustitución contradictoria produce una cláusula vacía.
            return CNF(self.num_vars, (tuple(),), new_fixed)
        new_fixed[variable] = bool(value)

        new_clauses: List[Tuple[int, ...]] = []
        for clause in self.clauses:
            reduced: List[int] = []
            clause_satisfied = False
            for lit in clause:
                if abs(lit) == variable:
                    literal_value = value if lit > 0 else not value
                    if literal_value:
                        clause_satisfied = True
                        break
                else:
                    reduced.append(lit)
            if not clause_satisfied:
                new_clauses.append(tuple(reduced))
        return CNF(self.num_vars, tuple(new_clauses), new_fixed)

    def free_variables(self) -> Tuple[int, ...]:
        return tuple(v for v in range(1, self.num_vars + 1) if v not in self.fixed)

    def fingerprint(self) -> str:
        data = repr((self.num_vars, self.clauses, tuple(sorted(self.fixed.items())))).encode()
        return hashlib.sha256(data).hexdigest()


Vector = Dict[int, int]


def _add_term(expr: Vector, index: int, coefficient: int, field: PrimeField) -> None:
    coefficient %= field.p
    if coefficient:
        expr[index] = (expr.get(index, 0) + coefficient) % field.p
        if expr[index] == 0:
            del expr[index]


def _constant(field: PrimeField, value: int = 1) -> Vector:
    return {0: value % field.p} if value % field.p else {}


def _variable(index: int) -> Vector:
    return {index: 1}


def _sub_expr(left: Vector, right: Vector, field: PrimeField) -> Vector:
    out: Vector = dict(left)
    for index, coefficient in right.items():
        _add_term(out, index, -coefficient, field)
    return out


def _eval_expr(expr: Mapping[int, int], witness: Sequence[int], field: PrimeField) -> int:
    return sum(coefficient * witness[index] for index, coefficient in expr.items()) % field.p


@dataclass(frozen=True)
class R1CSConstraint:
    A: Mapping[int, int]
    B: Mapping[int, int]
    C: Mapping[int, int]
    name: str

    def residual(self, witness: Sequence[int], field: PrimeField) -> int:
        a = _eval_expr(self.A, witness, field)
        b = _eval_expr(self.B, witness, field)
        c = _eval_expr(self.C, witness, field)
        return (a * b - c) % field.p


@dataclass(frozen=True)
class AuxiliaryDefinition:
    index: int
    A: Mapping[int, int]
    B: Mapping[int, int]


@dataclass
class R1CSInstance:
    field: PrimeField
    formula: CNF
    n_vars: int
    constraints: List[R1CSConstraint]
    auxiliary_definitions: List[AuxiliaryDefinition]

    @property
    def base_vars(self) -> int:
        return self.formula.num_vars

    def build_witness(self, assignment: Mapping[int, bool]) -> Tuple[int, ...]:
        """Construye el vector R1CS y calcula las auxiliares iterativamente."""
        if any(v not in assignment and v not in self.formula.fixed for v in range(1, self.base_vars + 1)):
            missing = [v for v in range(1, self.base_vars + 1) if v not in assignment and v not in self.formula.fixed]
            raise ValueError(f"faltan variables: {missing}")
        merged = dict(self.formula.fixed)
        merged.update({int(k): bool(v) for k, v in assignment.items()})
        witness = [0] * self.n_vars
        witness[0] = 1
        for var in range(1, self.base_vars + 1):
            witness[var] = int(merged.get(var, False))
        for definition in self.auxiliary_definitions:
            witness[definition.index] = (
                _eval_expr(definition.A, witness, self.field)
                * _eval_expr(definition.B, witness, self.field)
            ) % self.field.p
        return tuple(witness)

    def check_witness(self, witness: Sequence[int]) -> bool:
        return len(witness) == self.n_vars and all(
            constraint.residual(witness, self.field) == 0 for constraint in self.constraints
        )

    def residuals_by_group(self, witness: Sequence[int]) -> Dict[str, List[int]]:
        if len(witness) != self.n_vars:
            raise ValueError("longitud de testigo R1CS incorrecta")
        groups: Dict[str, List[int]] = {"booleanity": [], "fixed": [], "clauses": []}
        for constraint in self.constraints:
            if constraint.name.startswith("bool["):
                key = "booleanity"
            elif constraint.name.startswith("fixed["):
                key = "fixed"
            else:
                key = "clauses"
            groups[key].append(constraint.residual(witness, self.field))
        return groups

    def fingerprint(self) -> str:
        payload = repr(
            (
                self.formula.fingerprint(),
                self.n_vars,
                tuple((dict(c.A), dict(c.B), dict(c.C), c.name) for c in self.constraints),
            )
        ).encode()
        return hashlib.sha256(payload).hexdigest()


def Arithmetize(formula: CNF, field: Optional[PrimeField] = None) -> R1CSInstance:
    """Convierte una CNF a R1CS sobre F_p.

    Para cada x_i se añade x_i(x_i-1)=0. Para una cláusula, se añade la cadena
    que calcula prod_j(1-l_j) y finalmente se fuerza ese producto a cero.
    """
    F = field or PrimeField()
    constraints: List[R1CSConstraint] = []
    aux_defs: List[AuxiliaryDefinition] = []
    next_index = formula.num_vars + 1

    # Restricción booleana: x_i * (x_i - 1) = 0.
    for var in range(1, formula.num_vars + 1):
        A = _variable(var)
        B = _sub_expr(_variable(var), _constant(F), F)
        constraints.append(R1CSConstraint(A, B, {}, f"bool[x_{var}]") )

    # Las sustituciones ya conocidas se fijan algebraicamente.
    for var, value in sorted(formula.fixed.items()):
        constraints.append(
            R1CSConstraint(
                _variable(var),
                _constant(F),
                _constant(F, int(value)),
                f"fixed[x_{var}={int(value)}]",
            )
        )

    for clause_number, clause in enumerate(formula.clauses):
        # Cláusulas tautológicas no aportan una condición.
        if any(-lit in clause for lit in clause):
            continue
        if len(clause) == 0:
            constraints.append(
                R1CSConstraint(_constant(F), _constant(F), {}, f"clause[{clause_number}]-empty")
            )
            continue

        accumulator: Vector = _constant(F)
        for position, literal in enumerate(clause):
            var = abs(literal)
            # 1 - l: si l=x_i, es 1-x_i; si l=¬x_i, es x_i.
            factor = _sub_expr(_constant(F), _variable(var), F) if literal > 0 else _variable(var)
            aux_index = next_index
            next_index += 1
            constraints.append(
                R1CSConstraint(
                    accumulator,
                    factor,
                    _variable(aux_index),
                    f"clause[{clause_number}].prod[{position}]",
                )
            )
            aux_defs.append(AuxiliaryDefinition(aux_index, dict(accumulator), dict(factor)))
            accumulator = _variable(aux_index)
        constraints.append(
            R1CSConstraint(
                accumulator,
                _constant(F),
                {},
                f"clause[{clause_number}].zero",
            )
        )

    return R1CSInstance(F, formula, next_index, constraints, aux_defs)


@dataclass(frozen=True)
class LDE:
    """Tabla de evaluaciones de una extensión de bajo grado."""

    field: PrimeField
    base_values: Tuple[int, ...]
    base_domain: Tuple[int, ...]
    extended_domain: Tuple[int, ...]
    extended_values: Tuple[int, ...]
    barycentric_weights: Tuple[int, ...]
    original_length: int

    @property
    def degree_bound(self) -> int:
        return len(self.base_values) - 1

    def value_at(self, point: int) -> int:
        """Evalúa el polinomio interpolante en cualquier punto de F_p."""
        F = self.field
        x = point % F.p
        for node, value in zip(self.base_domain, self.base_values):
            if x == node:
                return value
        numerator = 0
        denominator = 0
        for node, value, weight in zip(self.base_domain, self.base_values, self.barycentric_weights):
            term = F.div(weight, x - node)
            numerator = (numerator + term * value) % F.p
            denominator = (denominator + term) % F.p
        return F.div(numerator, denominator)

    def query(self, index: int) -> int:
        if not 0 <= index < len(self.extended_values):
            raise IndexError("índice de consulta LDE fuera de rango")
        return self.extended_values[index]


def _next_power_of_two(n: int) -> int:
    size = 1
    while size < n:
        size <<= 1
    return size


def build_lde(values: Sequence[int], field: Optional[PrimeField] = None, factor: int = 4) -> LDE:
    """Construye la LDE explícita mediante interpolación baricéntrica."""
    F = field or PrimeField()
    if factor < 1 or factor & (factor - 1):
        raise ValueError("factor debe ser una potencia de 2 positiva")
    original_length = len(values)
    base_size = _next_power_of_two(max(1, original_length))
    extended_size = base_size * factor
    if (F.p - 1) % extended_size != 0:
        raise ValueError(
            f"el dominio extendido {extended_size} no divide p-1; reduzca el tamaño o elija otro primo"
        )
    padded = tuple(int(v) % F.p for v in values) + (0,) * (base_size - original_length)
    omega_ext = F.root_of_unity(extended_size)
    ext_domain = tuple(pow(omega_ext, i, F.p) for i in range(extended_size))
    base_domain = tuple(ext_domain[i * factor] for i in range(base_size))

    weights: List[int] = []
    for i, node_i in enumerate(base_domain):
        denominator = 1
        for j, node_j in enumerate(base_domain):
            if i != j:
                denominator = (denominator * (node_i - node_j)) % F.p
        weights.append(F.inv(denominator))

    lde = LDE(F, padded, base_domain, ext_domain, tuple(), tuple(weights), original_length)
    extended = tuple(lde.value_at(point) for point in ext_domain)
    return LDE(F, padded, base_domain, ext_domain, extended, tuple(weights), original_length)


@dataclass(frozen=True)
class PCPProof:
    """Stream holográfico basado en el witness R1CS, sin tabla de verdad.

    ``witness_lde`` codifica el vector R1CS completo (constante, variables y
    auxiliares) como un polinomio de bajo grado. La instancia R1CS es pública y
    el verificador consulta únicamente las posiciones del witness que aparecen
    en una fila seleccionada aleatoriamente.
    """

    instance_fingerprint: str
    witness: Tuple[int, ...]
    witness_lde: LDE
    constraint_count: int
    padded_constraint_count: int
    lde_factor: int


def ConstructPCPProof(
    arithmetized: R1CSInstance,
    witness: Mapping[int, bool] | Sequence[int],
    lde_factor: int = 4,
) -> PCPProof:
    """Genera el stream holográfico a partir del witness R1CS.

    No se construye ni se almacena la tabla de verdad. El prover solo encoda el
    vector ``z`` del witness R1CS en una LDE común. La instancia, sus filas y
    sus coeficientes son públicas para el verificador.
    """
    if lde_factor < 1 or lde_factor & (lde_factor - 1):
        raise ValueError("lde_factor debe ser una potencia de 2 positiva")
    A = arithmetized
    if isinstance(witness, Mapping):
        z = A.build_witness(witness)
    else:
        z = tuple(int(v) % A.field.p for v in witness)
    if len(z) != A.n_vars or not A.check_witness(z):
        raise ValueError("ConstructPCPProof recibió un testigo R1CS inválido")

    constraint_count = len(A.constraints)
    padded_constraint_count = _next_power_of_two(max(1, constraint_count))
    common_base_size = _next_power_of_two(max(1, len(z), padded_constraint_count))
    padded_witness = tuple(z) + (0,) * (common_base_size - len(z))
    witness_lde = build_lde(padded_witness, A.field, lde_factor)
    return PCPProof(
        A.fingerprint(),
        tuple(z),
        witness_lde,
        constraint_count,
        padded_constraint_count,
        lde_factor,
    )


def _constraint_domain_size(
    proof: Optional[PCPProof], arithmetized: R1CSInstance
) -> int:
    if proof is not None:
        return proof.padded_constraint_count
    return _next_power_of_two(max(1, len(arithmetized.constraints)))


def _row_witness_indices(constraint: R1CSConstraint) -> Tuple[int, ...]:
    indices = set(constraint.A) | set(constraint.B) | set(constraint.C)
    return tuple(sorted(indices))


def _constraint_residual_from_witness(
    arithmetized: R1CSInstance,
    proof: PCPProof,
    row_index: int,
) -> Tuple[int, Tuple[int, ...], Tuple[int, ...]]:
    """Versión compacta de la evaluación local, evitando reconstruir un vector."""
    F = arithmetized.field
    if row_index >= len(arithmetized.constraints):
        return 0, tuple(), tuple()
    constraint = arithmetized.constraints[row_index]
    indices = _row_witness_indices(constraint)
    values = tuple(
        proof.witness_lde.value_at(proof.witness_lde.base_domain[index])
        for index in indices
    )
    value_map = dict(zip(indices, values))
    a = sum(coefficient * value_map.get(index, 0) for index, coefficient in constraint.A.items()) % F.p
    b = sum(coefficient * value_map.get(index, 0) for index, coefficient in constraint.B.items()) % F.p
    c = sum(coefficient * value_map.get(index, 0) for index, coefficient in constraint.C.items()) % F.p
    return (a * b - c) % F.p, indices, values


def PCPVerifier(
    arithmetized: R1CSInstance,
    proof: PCPProof,
    r: Optional[int] = None,
    *,
    rng: Optional[random.Random] = None,
    strict: bool = False,
) -> bool:
    """Verifica una fila R1CS aleatoria usando el stream del witness LDE.

    La instancia R1CS es pública. Para la fila seleccionada solo se consultan
    las posiciones del witness que aparecen en A, B o C; una fila aritmetizada
    de CNF tiene anchura constante. ``strict=True`` mantiene la auditoría global.
    """
    if proof.instance_fingerprint != arithmetized.fingerprint():
        return False
    if proof.constraint_count != len(arithmetized.constraints):
        return False
    if proof.witness_lde.original_length < len(proof.witness):
        return False
    F = arithmetized.field
    if r is None:
        source = rng or random.SystemRandom()
        r = source.randrange(F.p)
    row_index = int(r) % proof.padded_constraint_count
    if strict and not arithmetized.check_witness(proof.witness):
        return False
    residual, indices, values = _constraint_residual_from_witness(arithmetized, proof, row_index)
    if any(
        proof.witness_lde.value_at(proof.witness_lde.base_domain[index]) != proof.witness[index]
        for index in indices
    ):
        return False
    return residual == 0


@dataclass(frozen=True)
class HolographicTranscript:
    """Transcript de una consulta holográfica del algoritmo del paper."""

    round_number: int
    variable: int
    branch_value: bool
    random_bits: Tuple[int, ...]
    query_index: Optional[int]
    field_point: Optional[int]
    oracle_names: Tuple[str, ...]
    oracle_values: Tuple[int, ...]
    proof_available: bool
    accepted: bool
    arithmetization_fingerprint: str

    @property
    def random_bit_count(self) -> int:
        return len(self.random_bits)

    @property
    def oracle_query_count(self) -> int:
        return len(self.oracle_names)


@dataclass(frozen=True)
class PaperMetrics:
    """Contadores reproducibles de la ejecución, separados de la semántica."""

    n_variables: int
    rounds: int
    total_random_bits: int
    total_oracle_queries: int
    materialized_proof_field_elements: int
    construction_seconds: float
    verification_seconds: float


@dataclass(frozen=True)
class PaperSearchResult:
    assignment: Mapping[int, bool]
    final_formula: CNF
    transcripts: Tuple[HolographicTranscript, ...]
    metrics: PaperMetrics


def _sample_random_bits(rng: random.Random, bit_count: int) -> Tuple[int, ...]:
    return tuple(rng.getrandbits(1) for _ in range(max(1, bit_count)))


def HolographicVerifier(
    arithmetized: R1CSInstance,
    proof: PCPProof,
    *,
    round_number: int = 0,
    variable: int = 0,
    branch_value: bool = False,
    rng: Optional[random.Random] = None,
    random_bits: Optional[Sequence[int]] = None,
    strict: bool = False,
) -> HolographicTranscript:
    """Verifica el stream del witness con una fila R1CS y consultas locales.

    El dominio de filas tiene tamaño potencia de dos. ``ceil(log2 |D|)`` bits
    seleccionan una fila; después solo se leen las posiciones del witness LDE
    que aparecen en los tres vectores dispersos de esa fila.
    """
    fingerprint = arithmetized.fingerprint()
    if proof.instance_fingerprint != fingerprint or proof.constraint_count != len(arithmetized.constraints):
        return HolographicTranscript(
            round_number, variable, branch_value, tuple(), None, None, tuple(), tuple(),
            False, False, fingerprint
        )

    domain_size = _constraint_domain_size(proof, arithmetized)
    bit_count = max(1, (domain_size - 1).bit_length())
    source = rng or random.Random()
    bits = (
        tuple(int(bit) & 1 for bit in random_bits)
        if random_bits is not None
        else _sample_random_bits(source, bit_count)
    )
    if len(bits) != bit_count:
        raise ValueError(f"se esperaban {bit_count} bits aleatorios, se recibieron {len(bits)}")
    query_index = 0
    for bit in bits:
        query_index = (query_index << 1) | bit
    field_point = proof.witness_lde.base_domain[query_index]
    residual, indices, values = _constraint_residual_from_witness(
        arithmetized, proof, query_index
    )
    names = tuple(f"witness[{index}]" for index in indices)
    accepted = residual == 0 and all(
        proof.witness_lde.value_at(proof.witness_lde.base_domain[index]) == proof.witness[index]
        for index in indices
    )
    if strict:
        accepted = accepted and arithmetized.check_witness(proof.witness)
    return HolographicTranscript(
        round_number,
        variable,
        branch_value,
        bits,
        query_index,
        field_point,
        names,
        values,
        True,
        accepted,
        fingerprint,
    )


WitnessOracle = Callable[[CNF], Optional[Mapping[int, bool] | Sequence[int]]]


def SearchToDecisionSAT(
    formula: CNF,
    witness_oracle: WitnessOracle,
    *,
    field: Optional[PrimeField] = None,
    rng: Optional[random.Random] = None,
    lde_factor: int = 4,
    strict_verification: bool = False,
) -> Dict[int, bool]:
    """Implementa la búsqueda incremental del pseudocódigo.

    El argumento ``witness_oracle`` representa la funcionalidad de decisión/PCP:
    devuelve un testigo para la fórmula restringida si es satisfacible y ``None``
    si es insatisfacible. La rutina no intenta reemplazar ese oráculo mediante
    enumeración de asignaciones; por ello no es un solver SAT autónomo.
    """
    F = field or PrimeField()
    random_source = rng or random.Random()
    current = formula
    assignment: Dict[int, bool] = {}

    for variable in range(1, formula.num_vars + 1):
        if variable in current.fixed:
            assignment[variable] = bool(current.fixed[variable])
            continue

        candidate_false = current.restrict(variable, False)
        candidate_arith = Arithmetize(candidate_false, F)
        candidate_witness = witness_oracle(candidate_false)
        accepted = False
        if candidate_witness is not None:
            proof = ConstructPCPProof(candidate_arith, candidate_witness, lde_factor)
            accepted = PCPVerifier(
                candidate_arith,
                proof,
                rng=random_source,
                strict=strict_verification,
            )
        if accepted:
            chosen = False
            current = candidate_false
        else:
            chosen = True
            current = current.restrict(variable, True)
            # Si el oráculo es correcto y la entrada original era satisfacible,
            # la rama verdadera debe admitir un testigo.
        assignment[variable] = chosen

    if not formula.evaluate(assignment):
        raise RuntimeError(
            "el oráculo de testigos rechazó una rama satisfacible o devolvió datos inconsistentes"
        )
    return assignment


def PaperSearchToDecisionSAT(
    formula: CNF,
    witness_oracle: WitnessOracle,
    *,
    field: Optional[PrimeField] = None,
    rng: Optional[random.Random] = None,
    lde_factor: int = 4,
    strict_verification: bool = False,
) -> PaperSearchResult:
    """Ejecuta el pseudocódigo del paper y conserva todo el transcript.

    Cada iteración genera `φ_⊥`, la aritmetiza, solicita una prueba, muestrea
    bits aleatorios y hace consultas directas al stream holográfico. La rama
    falsa se acepta exactamente cuando el transcript PCP es aceptado; de lo
    contrario se toma la rama verdadera, tal como en el algoritmo descrito.
    """
    F = field or PrimeField()
    source = rng or random.Random()
    current = formula
    assignment: Dict[int, bool] = {}
    transcripts: List[HolographicTranscript] = []
    total_random_bits = 0
    total_queries = 0
    materialized_elements = 0
    construction_seconds = 0.0
    verification_seconds = 0.0

    for round_number, variable in enumerate(range(1, formula.num_vars + 1), start=1):
        if variable in current.fixed:
            chosen = bool(current.fixed[variable])
            assignment[variable] = chosen
            transcripts.append(
                HolographicTranscript(
                    round_number, variable, chosen, tuple(), None, None, tuple(), tuple(),
                    True, True, "fixed"
                )
            )
            continue

        candidate_false = current.restrict(variable, False)
        arithmetized = Arithmetize(candidate_false, F)
        expected_domain_size = _constraint_domain_size(None, arithmetized)
        bit_count = max(1, (expected_domain_size - 1).bit_length())
        bits = _sample_random_bits(source, bit_count)
        total_random_bits += bit_count

        construction_start = time.perf_counter()
        candidate_witness = witness_oracle(candidate_false)
        proof: Optional[PCPProof] = None
        if candidate_witness is not None:
            proof = ConstructPCPProof(arithmetized, candidate_witness, lde_factor)
            materialized_elements += len(proof.witness_lde.extended_values)
        construction_seconds += time.perf_counter() - construction_start

        verification_start = time.perf_counter()
        if proof is None:
            transcript = HolographicTranscript(
                round_number,
                variable,
                False,
                bits,
                None,
                None,
                tuple(),
                tuple(),
                False,
                False,
                arithmetized.fingerprint(),
            )
        else:
            transcript = HolographicVerifier(
                arithmetized,
                proof,
                round_number=round_number,
                variable=variable,
                branch_value=False,
                rng=source,
                random_bits=bits,
                strict=strict_verification,
            )
        verification_seconds += time.perf_counter() - verification_start
        total_queries += transcript.oracle_query_count
        transcripts.append(transcript)

        if transcript.accepted:
            chosen = False
            current = candidate_false
        else:
            chosen = True
            current = current.restrict(variable, True)
        assignment[variable] = chosen

    if not formula.evaluate(assignment):
        raise RuntimeError("el transcript del paper terminó en una asignación no satisfactoria")
    metrics = PaperMetrics(
        formula.num_vars,
        len(transcripts),
        total_random_bits,
        total_queries,
        materialized_elements,
        construction_seconds,
        verification_seconds,
    )
    return PaperSearchResult(dict(assignment), current, tuple(transcripts), metrics)


def oracle_from_assignment(known_assignment: Mapping[int, bool]) -> WitnessOracle:
    """Oráculo de demostración: solo prueba fórmulas compatibles con un testigo conocido.

    Es suficiente para ejemplos donde el testigo conocido también decide todas las
    ramas consultadas. No es un sustituto de un oráculo SAT completo.
    """
    known = {int(k): bool(v) for k, v in known_assignment.items()}

    def oracle(formula: CNF) -> Optional[Mapping[int, bool]]:
        try:
            if formula.evaluate(known):
                return known
        except ValueError:
            return None
        return None

    return oracle


def _demo() -> None:
    # Esta instancia tiene como única asignación el patrón x1=0, x2=0, x3=1.
    formula = CNF.from_clauses(3, [(-1,), (-2,), (3,)])
    known = {1: False, 2: False, 3: True}
    F = PrimeField()
    A = Arithmetize(formula, F)
    z = A.build_witness(known)
    proof = ConstructPCPProof(A, z)
    print("R1CS válido:", A.check_witness(z))
    print("PCP local acepta:", PCPVerifier(A, proof, rng=random.Random(7)))
    print("tamaño witness LDE:", len(proof.witness_lde.base_values))
    recovered = SearchToDecisionSAT(
        formula,
        oracle_from_assignment(known),
        field=F,
        rng=random.Random(7),
    )
    print("asignación recuperada:", recovered)
    paper_result = PaperSearchToDecisionSAT(
        formula,
        oracle_from_assignment(known),
        field=F,
        rng=random.Random(7),
    )
    print("paper assignment:", dict(paper_result.assignment))
    print("paper metrics:", paper_result.metrics)
    print(
        "paper transcript:",
        [(t.variable, t.accepted, t.random_bit_count, t.oracle_query_count) for t in paper_result.transcripts],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CNF -> R1CS -> LDE -> PCP local")
    parser.add_argument("--demo", action="store_true", help="ejecuta una demostración pequeña")
    args = parser.parse_args()
    if args.demo:
        _demo()
    else:
        parser.error("use --demo o importe las funciones del módulo")


if __name__ == "__main__":
    main()
