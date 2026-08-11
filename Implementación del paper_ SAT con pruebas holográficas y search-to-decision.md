# Implementación del paper: SAT con pruebas holográficas y search-to-decision

## Resultado

Se extendió la base Python existente para ejecutar explícitamente el flujo descrito en el paper adjunto: aritmetización CNF→R1CS, codificación holográfica del witness mediante LDE, verificación local con bits aleatorios y consultas constantes de posiciones del witness, y reducción search-to-decision con transcript completo.

El núcleo de la extensión está en `cnf_pcp.py`. Las nuevas interfaces son `HolographicTranscript`, `HolographicVerifier`, `PaperMetrics`, `PaperSearchResult` y `PaperSearchToDecisionSAT`.

## Mapeo entre el algoritmo del paper y la implementación

| Paso del paper | Implementación |
|---|---|
| `φ_⊥ ← φ[x_i ← ⊥]` | `CNF.restrict(variable, False)` |
| `A_⊥ ← Arithmetize(φ_⊥)` | `Arithmetize(candidate_false, field)` |
| `π_⊥ ← ConstructPCPProof(A_⊥)` | `ConstructPCPProof(arithmetized, candidate_witness, lde_factor)`; construye `witness_lde` sin tabla de verdad |
| `r ← SampleRandomBits(O(log n))` | `_sample_random_bits(...)` |
| `PCPVerifier(A_⊥, π_⊥, r)` | `HolographicVerifier(..., random_bits=bits)` |
| Aceptación de la rama falsa | `transcript.accepted == True` |
| Rama verdadera | `current.restrict(variable, True)` |
| Resultado final | `PaperSearchResult.assignment` |

## Transcript y consultas

Cada `HolographicTranscript` registra la ronda, la variable, el valor de la rama consultada, los bits aleatorios, el índice del dominio, el punto de campo, los oráculos consultados, sus valores, la disponibilidad de la prueba y la decisión final.

El witness R1CS se interpola en un dominio LDE común. Para una ronda, la misma secuencia de bits selecciona una fila R1CS y el verificador consulta solamente las posiciones del witness que aparecen en A, B y C de esa fila. La anchura de cada fila CNF queda acotada por una constante, por lo que `oracle_query_count` es local e independiente del número total de restricciones.

## Validación ejecutada

La suite contiene ocho pruebas y terminó con estado `OK`. Verifica parsing DIMACS, sustitución de variables, satisfacción y rechazo de R1CS, interpolación LDE, rechazo de pruebas incompletas, ausencia de tabla de verdad, transcript holográfico y ejecución end-to-end del algoritmo del paper.

La demostración CLI se ejecutó con:

```bash
python3 cnf_pcp.py --demo
```

Resultado principal:

```text
paper assignment: {1: False, 2: False, 3: True}
paper transcript: [(1, True, 3, 2), (2, True, 3, 2), (3, False, 3, 0)]
```

El benchmark reproducible se ejecutó con:

```bash
python3 paper_benchmark.py 8 paper_benchmark.json
```

Para `n=8`, produjo 8 rondas, 40 bits aleatorios agregados, 13 consultas locales de witness y 448 elementos de campo materializados en las pruebas de la ejecución. El resultado JSON completo se incluye junto con este informe.

## Archivos

| Archivo | Contenido |
|---|---|
| `cnf_pcp.py` | Implementación completa de campo, CNF, R1CS, LDE, PCP y algoritmo del paper |
| `test_cnf_pcp.py` | Suite de pruebas automatizadas |
| `paper_benchmark.py` | Benchmark reproducible con semillas deterministas |
| `paper_benchmark.json` | Salida del benchmark hasta `n=8` |
| `paper_spec.md` | Especificación estructurada extraída del PDF |
| `README_cnf_pcp.md` | Guía de uso y explicación de las APIs |

## Ejecución

```bash
cd /home/ubuntu
python3 cnf_pcp.py --demo
python3 -m unittest -v test_cnf_pcp.py
python3 paper_benchmark.py 8 paper_benchmark.json
```

La construcción del witness LDE se mantiene explícita y no recursiva. La tabla de verdad fue eliminada del objeto de prueba y del camino de construcción. El objeto de prueba recibe el testigo proporcionado por el prover/oráculo y conserva la separación entre construcción, verificación y búsqueda incremental.

## Referencia

[1]: ./PNPinPolylogarithmicTimewithHolographicProofsandSearch-to-DecisionReduction(7).pdf "Paper adjunto: P=NP in Polylogarithmic Time with Holographic Proofs and Search-to-Decision Reduction"
