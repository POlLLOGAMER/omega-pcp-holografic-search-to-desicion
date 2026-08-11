# Especificación extraída del paper

## Algoritmo declarado

El paper propone combinar una reducción search-to-decision de SAT con verificación PCP/holográfica. Para una fórmula satisfacible `φ` sobre `n` variables, se fija cada variable con una consulta a la versión restringida:

1. Construir `φ_⊥ = φ[x_i ← ⊥]`.
2. Arithmetizar `φ_⊥`.
3. Construir una prueba holográfica `π_⊥`.
4. Muestrear `O(log n)` bits aleatorios.
5. Ejecutar el verificador PCP con un número constante de consultas.
6. Si acepta, fijar `x_i = 0`; si rechaza, fijar `x_i = 1`.

El mismo proceso se repite para las variables restantes.

## Componentes y afirmaciones del texto

| Componente | Especificación del paper |
|---|---|
| Entrada | Fórmula booleana `φ(x_1,...,x_n)` |
| Arithmetization | Codificar la fórmula como restricciones polinomiales de bajo grado |
| Proof construction | Generar prueba holográfica / transparent proof |
| Randomness | `O(log n)` bits por consulta |
| Verification | Leer `O(1)` bits de la prueba |
| Search-to-decision | `O(log n)` consultas |
| Complejidad declarada | `O(log^2 n)` |
| Conclusión declarada | SAT en tiempo polilogarítmico y `P=NP` |

## Correspondencia con la base existente

- `CNF` representa la fórmula y ofrece `restrict(variable, value)`.
- `Arithmetize` convierte las cláusulas a R1CS sobre `F_p`.
- `ConstructPCPProof` codifica el vector witness R1CS completo como una LDE de bajo grado.
- `PCPVerifier` selecciona una fila R1CS y consulta las posiciones del witness usadas por esa fila.
- `SearchToDecisionSAT` ejecuta la fijación variable a variable usando un `witness_oracle`.

## Extensión requerida para implementar el paper como artefacto reproducible

1. Modelar explícitamente el stream holográfico como la LDE del witness R1CS, sin tabla de verdad.
2. Convertir el punto aleatorio `r` a un vector de `O(log n)` bits y registrar la semilla.
3. Seleccionar una fila R1CS y consultar solamente las posiciones del witness que aparecen en A, B y C.
4. Mantener separado el prover (`ConstructPCPProof`) del verificador (`HolographicVerifier`).
5. Añadir instrumentación de conteo de consultas, bits aleatorios, tamaño de prueba, tiempo de construcción y tiempo de verificación.
6. Validar cada componente mediante propiedades algebraicas y pruebas de extremo a extremo.

## Decisiones de implementación

La construcción LDE se mantiene explícita y no recursiva. La interfaz del prover recibe un testigo, porque el pseudocódigo presupone una prueba válida para cada consulta. La verificación registrará consultas constantes a los oráculos y separará ese número de consultas del coste interno de evaluar una interpolación explícita.
