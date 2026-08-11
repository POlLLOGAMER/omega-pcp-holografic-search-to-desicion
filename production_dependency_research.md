# Evaluación inicial de dependencias profesionales

## Fuentes consultadas

| Proyecto | URL | Hallazgo |
|---|---|---|
| arkworks algebra | https://github.com/arkworks-rs/algebra | Rust; implementa campos finitos, curvas y polinomios; licencia dual Apache-2.0/MIT; repositorio activo |
| arkworks poly-commit | https://github.com/arkworks-rs/poly-commit | Rust; seis familias de polynomial commitments, incluyendo IPA, KZG/Marlin, Sonic/AuroraLight, Hyrax, Ligero y Brakedown; licencia dual Apache-2.0/MIT |
| Aurora | https://link.springer.com/chapter/10.1007/978-3-030-17653-2_4 | Referencia de IOP/R1CS transparente; usa códigos Reed–Solomon y un IOP de sumcheck univariado |
| Polaris | https://petsymposium.org/popets/2022/popets-2022-0027.php | Argumento transparente para R1CS y polynomial commitments; sirve como referencia de arquitectura |

## Decisión provisional

La ruta profesional será un backend Rust separado, invocable desde Python, en lugar de importar código Rust dentro de un módulo Python artesanal. `arkworks-algebra` reemplazará la aritmética de campo y polinomios; `arkworks-poly-commit` aportará compromisos polinomiales cuando la configuración de seguridad y el esquema elegido sean compatibles.

El backend mantendrá la semántica witness-only: la prueba se construye a partir del vector R1CS y no genera ninguna tabla de verdad. La capa Python conservará CNF, aritmetización, search-to-decision y serialización del transcript; el backend Rust recibirá una instancia R1CS serializada y devolverá el commitment, las aperturas y el resultado de verificación.

## Restricciones identificadas

`arkworks-poly-commit` declara en su README que es un prototipo académico y advierte que no ha recibido una revisión cuidadosa para uso en producción. Por ello se puede integrar como backend profesional/reproducible de investigación, pero la documentación debe conservar la advertencia de auditoría y no atribuirle una certificación de producción que el repositorio no afirma.

Para una prueba transparente sin trusted setup, KZG no será la elección por defecto. Se priorizará IPA o Ligero/Brakedown según la disponibilidad de APIs estables y la compatibilidad con el campo. FRI completo puede requerir integrar Plonky3 o una implementación especializada; no se copiará código desde GitHub sin fijar commit, licencia y pruebas.

## Próximos pasos de integración

1. Fijar versiones/commits y revisar Cargo.toml, licencias y MSRV.
2. Crear un crate `production_backend` con tipos serializables para R1CS, witness LDE, commitment y transcript.
3. Añadir una interfaz Python que invoque el binario o una extensión controlada.
4. Comparar los resultados del backend con las pruebas Python existentes.
5. Ejecutar pruebas de corrupción, round-trip, determinismo, límites de campo y benchmarks.
