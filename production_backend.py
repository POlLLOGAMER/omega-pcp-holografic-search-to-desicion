"""Puente Python -> backend Rust profesional basado en Arkworks.

El backend Rust usa Arkworks para F_p, FFT/IFFT, polinomios y serialización de
campo. Esta capa mantiene CNF/R1CS en Python y transporta solo JSON estructurado.
La prueba es witness-only: no se genera tabla de verdad.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
from typing import Any, Mapping, Optional, Sequence, Tuple

from cnf_pcp import R1CSInstance


DEFAULT_BACKEND = Path(__file__).resolve().parent / "production_backend" / "target" / "release" / "production_backend"


class ProductionBackendError(RuntimeError):
    """Error controlado del backend Rust o de la serialización R1CS."""


@dataclass(frozen=True)
class ProductionProof:
    instance_fingerprint: str
    witness: Tuple[int, ...]
    payload: Mapping[str, Any]

    @property
    def commitment(self) -> str:
        return str(self.payload["merkle_root"])

    @property
    def backend(self) -> str:
        return str(self.payload["backend"])

    @property
    def extended_size(self) -> int:
        return len(self.payload["extended_values"])

    def to_json(self) -> str:
        return json.dumps(
            {
                "instance_fingerprint": self.instance_fingerprint,
                "witness": list(self.witness),
                "payload": self.payload,
            },
            indent=2,
            sort_keys=True,
        )


def _backend_path(path: Optional[os.PathLike[str] | str]) -> Path:
    selected = Path(path or os.environ.get("PRODUCTION_BACKEND_BIN", DEFAULT_BACKEND))
    if not selected.is_file() or not os.access(selected, os.X_OK):
        raise ProductionBackendError(
            f"backend Rust no encontrado o no ejecutable: {selected}. "
            "Compile production_backend con cargo build --release."
        )
    return selected


def _sparse_expr(expr: Mapping[int, int]) -> list[list[int]]:
    return [[int(index), int(coefficient)] for index, coefficient in sorted(expr.items())]


def _instance_json(instance: R1CSInstance, witness: Sequence[int]) -> dict[str, Any]:
    if len(witness) != instance.n_vars:
        raise ProductionBackendError("longitud de witness incompatible con R1CS")
    constraints = []
    for constraint in instance.constraints:
        constraints.append(
            {
                "a": _sparse_expr(constraint.A),
                "b": _sparse_expr(constraint.B),
                "c": _sparse_expr(constraint.C),
            }
        )
    return {"witness": [int(value) % instance.field.p for value in witness], "constraints": constraints}


def _run_backend(binary: Path, args: Sequence[str], cwd: Path) -> str:
    process = subprocess.run(
        [str(binary), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        details = (process.stderr or process.stdout).strip()
        raise ProductionBackendError(details or f"backend terminó con código {process.returncode}")
    return process.stdout


def ConstructProductionProof(
    arithmetized: R1CSInstance,
    witness: Mapping[int, bool] | Sequence[int],
    *,
    backend_binary: Optional[os.PathLike[str] | str] = None,
) -> ProductionProof:
    """Construye una prueba usando Arkworks y un Merkle commitment del witness LDE."""
    if isinstance(witness, Mapping):
        z = arithmetized.build_witness(witness)
    else:
        z = tuple(int(value) % arithmetized.field.p for value in witness)
    if len(z) != arithmetized.n_vars or not arithmetized.check_witness(z):
        raise ProductionBackendError("witness R1CS inválido")
    binary = _backend_path(backend_binary)
    with tempfile.TemporaryDirectory(prefix="r1cs-production-") as directory:
        root = Path(directory)
        input_path = root / "instance.json"
        proof_path = root / "proof.json"
        input_path.write_text(json.dumps(_instance_json(arithmetized, z)), encoding="utf-8")
        _run_backend(binary, ["build", str(input_path), str(proof_path)], root)
        payload = json.loads(proof_path.read_text(encoding="utf-8"))
    return ProductionProof(arithmetized.fingerprint(), tuple(z), payload)


def VerifyProductionProof(
    arithmetized: R1CSInstance,
    proof: ProductionProof,
    *,
    row: Optional[int] = None,
    backend_binary: Optional[os.PathLike[str] | str] = None,
) -> bool:
    """Verifica la prueba Rust, su LDE/commitment y una fila local R1CS."""
    if proof.instance_fingerprint != arithmetized.fingerprint():
        return False
    binary = _backend_path(backend_binary)
    selected_row = 0 if row is None else int(row) % max(1, len(arithmetized.constraints))
    with tempfile.TemporaryDirectory(prefix="r1cs-production-verify-") as directory:
        root = Path(directory)
        input_path = root / "instance.json"
        proof_path = root / "proof.json"
        input_path.write_text(json.dumps(_instance_json(arithmetized, proof.witness)), encoding="utf-8")
        proof_path.write_text(json.dumps(proof.payload), encoding="utf-8")
        try:
            _run_backend(binary, ["verify", str(input_path), str(proof_path), str(selected_row)], root)
        except ProductionBackendError:
            return False
    return True


def ProductionProofTranscript(
    arithmetized: R1CSInstance,
    proof: ProductionProof,
    *,
    row: int,
    rng: Optional[random.Random] = None,
    backend_binary: Optional[os.PathLike[str] | str] = None,
) -> dict[str, Any]:
    """Devuelve un transcript estructurado con seed, fila, commitment y resultado."""
    source = rng or random.SystemRandom()
    domain_size = max(1, proof.payload["base_size"])
    bit_count = max(1, (domain_size - 1).bit_length())
    bits = tuple(source.getrandbits(1) for _ in range(bit_count))
    selected_row = int(row) % max(1, len(arithmetized.constraints))
    accepted = VerifyProductionProof(
        arithmetized,
        proof,
        row=selected_row,
        backend_binary=backend_binary,
    )
    return {
        "backend": proof.backend,
        "commitment": proof.commitment,
        "row": selected_row,
        "random_bits": list(bits),
        "random_bit_count": bit_count,
        "accepted": accepted,
        "witness_lde_size": proof.extended_size,
    }


def ProductionPaperSearchToDecisionSAT(
    formula: Any,
    witness_oracle: Any,
    *,
    field: Optional[Any] = None,
    rng: Optional[random.Random] = None,
    backend_binary: Optional[os.PathLike[str] | str] = None,
) -> dict[str, Any]:
    """Ejecuta la búsqueda incremental usando pruebas construidas en Rust.

    La fórmula y la aritmetización siguen en Python; la prueba witness-only,
    FFT/IFFT, serialización de campo y commitment se ejecutan en Arkworks.
    """
    from cnf_pcp import Arithmetize

    prime_field = field
    source = rng or random.Random()
    current = formula
    assignment: dict[int, bool] = {}
    transcripts: list[dict[str, Any]] = []

    for round_number, variable in enumerate(range(1, formula.num_vars + 1), start=1):
        if variable in current.fixed:
            chosen = bool(current.fixed[variable])
            assignment[variable] = chosen
            transcripts.append(
                {
                    "round": round_number,
                    "variable": variable,
                    "branch": chosen,
                    "proof_available": True,
                    "accepted": True,
                    "skipped_fixed": True,
                }
            )
            continue

        candidate_false = current.restrict(variable, False)
        instance = Arithmetize(candidate_false, prime_field)
        candidate_witness = witness_oracle(candidate_false)
        if candidate_witness is None:
            chosen = True
            current = current.restrict(variable, True)
            assignment[variable] = chosen
            transcripts.append(
                {
                    "round": round_number,
                    "variable": variable,
                    "branch": False,
                    "proof_available": False,
                    "accepted": False,
                }
            )
            continue

        proof = ConstructProductionProof(
            instance,
            candidate_witness,
            backend_binary=backend_binary,
        )
        row_domain = max(1, len(instance.constraints))
        selected_row = source.randrange(row_domain)
        transcript = ProductionProofTranscript(
            instance,
            proof,
            row=selected_row,
            rng=source,
            backend_binary=backend_binary,
        )
        transcript.update(
            {
                "round": round_number,
                "variable": variable,
                "branch": False,
                "proof_available": True,
            }
        )
        transcripts.append(transcript)
        if transcript["accepted"]:
            chosen = False
            current = candidate_false
        else:
            chosen = True
            current = current.restrict(variable, True)
        assignment[variable] = chosen

    if not formula.evaluate(assignment):
        raise ProductionBackendError("la búsqueda profesional terminó en una asignación inválida")
    return {
        "assignment": assignment,
        "final_formula": current,
        "transcripts": tuple(transcripts),
        "backend": "arkworks-rs/algebra",
    }
