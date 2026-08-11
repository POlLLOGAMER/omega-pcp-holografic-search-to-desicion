# Aritmetización CNF–R1CS–LDE–PCP en Python

Este repositorio contiene una implementación educativa y ejecutable del flujo algebraico solicitado. El archivo principal es [`cnf_pcp.py`](./cnf_pcp.py) y las pruebas están en [`test_cnf_pcp.py`](./test_cnf_pcp.py).

> **Punto importante.** Un verificador PCP no decide por sí solo si una instancia SAT es satisfacible: verifica una prueba proporcionada por un prover. Por tanto, `ConstructPCPProof` recibe un testigo válido y `SearchToDecisionSAT` recibe `witness_oracle`, que representa el prover/oráculo de decisión del pseudocódigo. El módulo no disfraza una enumeración exponencial como si fuera un algoritmo polinomial.

## Modelo matemático

Para una cláusula `C = (l_1 ∨ ... ∨ l_k)`, con literales booleanos `l_j ∈ {0,1}`, se utiliza

```text
prod_j (1 - l_j) = 0.
```

La igualdad se cumple exactamente cuando al menos un literal es verdadero. Cada producto se implementa como una cadena de restricciones R1CS de la forma `A(z) B(z) = C(z)`. Además, para cada variable se añade

```text
x_i (x_i - 1) = 0,
```

que fuerza a `x_i` a ser booleano sobre un campo de característica distinta de dos. Las variables auxiliares de las cadenas de producto se calculan iterativamente, sin recursión.

El campo por defecto es

```text
F_p,  p = 2_013_265_921 = 15 · 2^27 + 1.
```

Este primo permite construir dominios multiplicativos de tamaño potencia de dos para los ejemplos incluidos. La clase `PrimeField` también acepta otro primo, siempre que el tamaño del dominio LDE elegido divida `p - 1`.

## Interfaz principal

| Función | Papel | Complejidad o característica |
|---|---|---|
| `Arithmetize(formula, field)` | Convierte CNF en una instancia R1CS | Lineal en el tamaño de la CNF, aparte de la aritmética del campo |
| `R1CSInstance.build_witness(assignment)` | Construye el vector R1CS y las auxiliares | Iterativa; no enumera asignaciones |
| `build_lde(values, field, factor)` | Interpola y evalúa una extensión de bajo grado | LDE explícita, transparente; la construcción usa interpolación baricéntrica |
| `ConstructPCPProof(instance, witness)` | Codifica el witness R1CS completo en una LDE | No enumera asignaciones booleanas; materializa solo el stream del witness |
| `PCPVerifier(instance, proof, r)` | Selecciona una fila R1CS y consulta las posiciones de witness usadas por ella | Anchura constante por fila; no consulta la fórmula completa |
| `SearchToDecisionSAT(formula, witness_oracle)` | Sigue la búsqueda incremental base | Requiere un prover/oráculo de testigos; no usa Z3 ni un solver externo |
| `HolographicVerifier(instance, proof, random_bits)` | Convierte bits aleatorios en un índice del dominio y consulta cada oráculo una vez | Registra transcript y realiza `O(1)` consultas |
| `PaperSearchToDecisionSAT(formula, witness_oracle)` | Ejecuta el algoritmo del paper, ronda por ronda | Devuelve asignación, transcript y métricas reproducibles |

En esta implementación transparente, una consulta `value_at(r)` usa interpolación baricéntrica y cuesta tiempo lineal en el tamaño de la base LDE del witness. Eso no contradice la propiedad de **consulta constante** del verificador: la propiedad PCP se refiere al número de posiciones consultadas en la palabra/oráculo, no a una implementación ingenua de la evaluación polinomial. Un esquema de compromiso polinomial sustituiría esta evaluación explícita en una implementación criptográfica.

## Ejemplo ejecutable

```bash
python3 cnf_pcp.py --demo
```

La demostración construye la fórmula

```text
(¬x_1) ∧ (¬x_2) ∧ (x_3),
```

genera su testigo R1CS, construye la LDE, verifica la prueba en un punto aleatorio y recupera la asignación `{1: False, 2: False, 3: True}` mediante el algoritmo incremental.

## Entrada DIMACS

El parser acepta CNF DIMACS estándar:

```python
from cnf_pcp import CNF, Arithmetize, PrimeField

text = """
p cnf 3 2
1 -2 0
3 0
"""
formula = CNF.from_dimacs(text)
instance = Arithmetize(formula, PrimeField())
```

Los literales positivos representan `x_i` y los negativos representan `¬x_i`. Las cláusulas tautológicas se ignoran al aritmetizar porque son siempre verdaderas. Las cláusulas vacías producen una restricción imposible.

## Uso del verificador

```python
from cnf_pcp import (
    CNF, PrimeField, Arithmetize, ConstructPCPProof, PCPVerifier
)

formula = CNF.from_clauses(2, [(1,), (-2,)])
field = PrimeField()
instance = Arithmetize(formula, field)
witness = instance.build_witness({1: True, 2: False})
proof = ConstructPCPProof(instance, witness, lde_factor=4)

accepted = PCPVerifier(instance, proof, rng=None)
assert accepted
```

`PCPVerifier(..., strict=False)` selecciona una fila R1CS y consulta localmente el witness LDE. Para tests, `strict=True` también audita directamente todas las restricciones contra el testigo incluido en la prueba. Una prueba incompleta, con fingerprint incompatible o con residuos no nulos se rechaza.

`HolographicVerifier` corresponde directamente a la descripción de bits aleatorios y consultas constantes del paper: los bits seleccionan una fila del dominio R1CS y después se leen únicamente las posiciones del witness LDE que aparecen en A, B y C de esa fila.

## Implementación explícita del paper

La función `PaperSearchToDecisionSAT` conserva el flujo del algoritmo en un objeto `PaperSearchResult`. Cada ronda contiene un `HolographicTranscript` con la variable, la rama candidata, los bits aleatorios, el índice de consulta, el punto de campo, los nombres y valores de los oráculos consultados y la decisión del verificador. `PaperMetrics` agrega el número de rondas, bits aleatorios, consultas de oráculo, elementos materializados de las pruebas y tiempos separados de construcción y verificación.

```python
from cnf_pcp import CNF, PaperSearchToDecisionSAT, oracle_from_assignment
import random

formula = CNF.from_clauses(3, [(-1,), (-2,), (3,)])
result = PaperSearchToDecisionSAT(
    formula,
    oracle_from_assignment({1: False, 2: False, 3: True}),
    rng=random.Random(7),
)
print(dict(result.assignment))
for transcript in result.transcripts:
    print(transcript.variable, transcript.accepted,
          transcript.random_bit_count, transcript.oracle_query_count)
print(result.metrics)
```

`HolographicVerifier` usa una única secuencia de bits aleatorios para seleccionar una fila R1CS. Después consulta solo las posiciones del witness LDE que aparecen en los vectores dispersos A, B y C de esa fila. La implementación materializa el witness LDE explícitamente y separa en las métricas el coste de construirlo del coste de las consultas locales.

## Búsqueda incremental

La función de búsqueda recibe explícitamente un oráculo de testigos:

```python
from cnf_pcp import SearchToDecisionSAT, oracle_from_assignment

known = {1: True, 2: False}
assignment = SearchToDecisionSAT(
    formula,
    oracle_from_assignment(known),
)
```

`oracle_from_assignment` es solo un adaptador de demostración para un testigo ya conocido. En una construcción PCP real, el prover produciría una palabra de prueba a partir de un testigo y el verificador comprobaría las restricciones mediante un protocolo de compromiso/consulta.

## Stream holográfico sin tabla de verdad

La prueba ya no construye la función booleana sobre todas las asignaciones. El prover recibe el witness R1CS válido, lo interpola en un polinomio de bajo grado y publica su LDE como stream holográfico. La instancia R1CS es pública; una consulta selecciona una fila y lee únicamente las entradas del witness que aparecen en sus vectores A, B y C.

Para una fila seleccionada se calcula localmente `A(z) · B(z) - C(z)`. La aceptación requiere que ese residuo sea cero y que las posiciones leídas del stream coincidan con las posiciones base del witness. El número de posiciones leídas por fila está acotado por la anchura de la restricción y no depende del número total de filas.

`oracle_from_assignment` continúa siendo un adaptador de demostración para un testigo conocido. En el flujo holográfico, `ConstructPCPProof` materializa únicamente `witness_lde`; no existe un campo `truth_table_lde` en `PCPProof`.


## Benchmark reproducible

El archivo `paper_benchmark.py` ejecuta la versión del paper sobre la familia `(¬x_1) ∧ ... ∧ (¬x_{n-1}) ∧ x_n`, con un testigo conocido y semilla determinista. Guarda las métricas en JSON y muestra el número de rondas, bits aleatorios, consultas de oráculo, elementos materializados de la prueba y tiempos separados.

```bash
python3 paper_benchmark.py 8 paper_benchmark.json
```

El benchmark no sustituye una demostración matemática; sirve para inspeccionar el transcript y comprobar que la implementación sigue el flujo del paper de forma reproducible.

## Pruebas

```bash
python3 -m unittest -v test_cnf_pcp.py
python3 -m py_compile cnf_pcp.py test_cnf_pcp.py
```

Las pruebas cubren parsing DIMACS, sustitución de variables, aceptación y rechazo R1CS, interpolación de la LDE en el dominio base, rechazo de pruebas incompletas o testigos inválidos, transcripts holográficos y recuperación incremental con un oráculo conocido.

## Referencias

[1]: https://www.cs.princeton.edu/~arora/pubs/PCP.pdf "Probabilistically Checkable Proofs and the Hardness of Approximation"

[2]: https://eprint.iacr.org/2012/215 "Pinocchio: Nearly Practical Verifiable Computation"

[3]: https://en.wikipedia.org/wiki/Low-degree_extension "Low-degree extension"
