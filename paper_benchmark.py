"""Benchmark reproducible de PaperSearchToDecisionSAT.

La familia usada es:
    (¬x_1) ∧ ... ∧ (¬x_{n-1}) ∧ x_n,
con testigo conocido x_1=...=x_{n-1}=0, x_n=1.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from cnf_pcp import CNF, PaperSearchToDecisionSAT, oracle_from_assignment


def run(max_n: int = 8) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for n in range(1, max_n + 1):
        clauses = [(-variable,) for variable in range(1, n)] + [(n,)]
        formula = CNF.from_clauses(n, clauses)
        known = {variable: False for variable in range(1, n)}
        known[n] = True
        result = PaperSearchToDecisionSAT(
            formula,
            oracle_from_assignment(known),
            rng=random.Random(10_000 + n),
            lde_factor=2,
        )
        metrics = result.metrics
        rows.append(
            {
                "n": n,
                "rounds": metrics.rounds,
                "random_bits": metrics.total_random_bits,
                "oracle_queries": metrics.total_oracle_queries,
                "proof_field_elements": metrics.materialized_proof_field_elements,
                "construction_seconds": metrics.construction_seconds,
                "verification_seconds": metrics.verification_seconds,
                "assignment": dict(result.assignment),
            }
        )
    return rows


def main() -> None:
    max_n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    rows = run(max_n)
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("paper_benchmark.json")
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(output)
    for row in rows:
        print(
            row["n"],
            "rounds=", row["rounds"],
            "bits=", row["random_bits"],
            "queries=", row["oracle_queries"],
            "proof_elements=", row["proof_field_elements"],
            "build_s=", f"{row['construction_seconds']:.6f}",
            "verify_s=", f"{row['verification_seconds']:.6f}",
        )


if __name__ == "__main__":
    main()
