# Backend witness-only orientado a producción

## Arquitectura

La implementación ahora separa la lógica de alto nivel y el núcleo algebraico:

| Capa | Implementación | Responsabilidad |
|---|---|---|
| Fórmula y reducción | `cnf_pcp.py` | CNF, restricción de variables, aritmetización R1CS y search-to-decision |
| Núcleo algebraico | `production_backend/` | Campo finito, dominios de evaluación, FFT/IFFT, LDE y serialización |
| Puente | `production_backend.py` | Serializa R1CS/witness, invoca el binario Rust y reconstruye transcripts |
| Validación | `test_production_backend.py` | Round-trip, commitments, filas locales, instancia incorrecta y búsqueda completa |

El backend Rust usa `ark-ff`, `ark-poly` y `ark-serialize` desde el repositorio de Arkworks fijado por commit. El campo es `F_p` con `p = 2_013_265_921`, y la LDE se construye mediante `GeneralEvaluationDomain`, `ifft_in_place` y `fft_in_place`. El commitment del stream extendido usa una raíz Merkle SHA-256 sobre serializaciones canónicas de campo.

## Dependencias fijadas

```text
arkworks-rs/algebra
commit: 57be20e56a142b059bca05653961f8a9ca4f54ae
crates: ark-ff, ark-poly, ark-serialize
licencia declarada: Apache-2.0 o MIT
```

La cadena completa queda bloqueada en `production_backend/Cargo.lock`. La compilación requiere Rust estable; el entorno usado para validar esta versión fue `rustc 1.97.1` y `cargo 1.97.1`.

## Construcción y verificación

```bash
source /home/ubuntu/.cargo/env
cd /home/ubuntu/production_backend
cargo fmt -- --check
cargo build --release

./target/release/production_backend \
  build example_input.json example_proof.json

./target/release/production_backend \
  verify example_input.json example_proof.json 0
```

La prueba JSON contiene el esquema, el backend, el módulo del campo, el tamaño base, el factor de extensión, las evaluaciones base y extendidas y la raíz Merkle. El verificador comprueba de nuevo las evaluaciones LDE, la raíz, la longitud del witness, la instancia y la fila R1CS seleccionada.

## Uso desde Python

```python
from cnf_pcp import CNF, Arithmetize, PrimeField
from production_backend import (
    ConstructProductionProof,
    VerifyProductionProof,
    ProductionPaperSearchToDecisionSAT,
)

field = PrimeField()
formula = CNF.from_clauses(2, [(1,), (-2,)])
instance = Arithmetize(formula, field)
proof = ConstructProductionProof(instance, {1: True, 2: False})
assert VerifyProductionProof(instance, proof, row=0)
```

Para ejecutar la búsqueda completa con el backend Rust por ronda:

```python
result = ProductionPaperSearchToDecisionSAT(
    formula,
    lambda candidate: {1: True, 2: False}
        if candidate.evaluate({1: True, 2: False}) else None,
    field=field,
)
```

## Validación realizada

La compilación release terminó correctamente después de fijar Rust estable y generar `Cargo.lock`. El round-trip CLI construyó una prueba con dominio base de tamaño 4, dominio extendido de tamaño 16 y commitment determinista; las filas R1CS 0, 1 y 2 fueron aceptadas. La suite Python de interoperabilidad terminó con **4 pruebas exitosas** y la suite base witness-only con **8 pruebas exitosas**.

## Alcance de la garantía

Esta integración mejora de forma sustancial la calidad de ingeniería: usa implementaciones mantenidas de campo y polinomios, aritmética canónica, FFT/IFFT de dominio estructurado, lockfile, binario aislado, serialización explícita, detección de corrupción y pruebas de interoperabilidad. El commitment Merkle incluido es un commitment de integridad del stream completo; no pretende ser por sí solo un sistema completo de polynomial commitment con aperturas sucintas, FRI o soundness criptográfico del PCP. Esos componentes requieren integrar un protocolo PCS/FRI completo y sus parámetros de seguridad, no solo sustituir una clase de Python.

Arkworks declara que algunos repositorios del ecosistema son de investigación y deben auditarse antes de producción. Por esa razón el paquete documenta exactamente qué parte está respaldada por Arkworks y qué parte sigue siendo el adaptador/protocolo específico del proyecto, sin presentar el prototipo como un SNARK auditado.

## Referencias

[1]: https://github.com/arkworks-rs/algebra "Arkworks algebra: finite field, elliptic curve, and polynomial arithmetic"

[2]: https://github.com/arkworks-rs/poly-commit "Arkworks polynomial commitment library"

[3]: https://link.springer.com/chapter/10.1007/978-3-030-17653-2_4 "Aurora: Transparent Succinct Arguments for R1CS"
