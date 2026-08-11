import random
import unittest

from cnf_pcp import Arithmetize, CNF, PrimeField
from production_backend import (
    ConstructProductionProof,
    ProductionProofTranscript,
    ProductionPaperSearchToDecisionSAT,
    VerifyProductionProof,
)


class ProductionBackendTests(unittest.TestCase):
    def setUp(self):
        self.field = PrimeField()
        self.formula = CNF.from_clauses(2, [(1,), (-2,)])
        self.instance = Arithmetize(self.formula, self.field)
        self.assignment = {1: True, 2: False}

    def test_round_trip_arkworks_backend(self):
        proof = ConstructProductionProof(self.instance, self.assignment)
        self.assertEqual(proof.instance_fingerprint, self.instance.fingerprint())
        self.assertEqual(proof.backend, "arkworks-rs/algebra@57be20e56a142b059bca05653961f8a9ca4f54ae")
        self.assertEqual(len(proof.witness), self.instance.n_vars)
        self.assertGreater(proof.extended_size, len(proof.witness))
        self.assertTrue(VerifyProductionProof(self.instance, proof, row=0))
        self.assertTrue(VerifyProductionProof(self.instance, proof, row=1))

    def test_transcript_contains_commitment_and_randomness(self):
        proof = ConstructProductionProof(self.instance, self.assignment)
        transcript = ProductionProofTranscript(
            self.instance,
            proof,
            row=0,
            rng=random.Random(7),
        )
        self.assertTrue(transcript["accepted"])
        self.assertEqual(transcript["commitment"], proof.commitment)
        self.assertGreater(transcript["random_bit_count"], 0)
        self.assertGreater(transcript["witness_lde_size"], 0)

    def test_production_search_to_decision(self):
        formula = CNF.from_clauses(3, [(-1,), (-2,), (3,)])
        known = {1: False, 2: False, 3: True}
        result = ProductionPaperSearchToDecisionSAT(
            formula,
            lambda candidate: known if candidate.evaluate(known) else None,
            field=self.field,
            rng=random.Random(23),
        )
        self.assertEqual(result["assignment"], known)
        self.assertTrue(formula.evaluate(result["assignment"]))
        self.assertEqual(len(result["transcripts"]), 3)

    def test_wrong_instance_is_rejected(self):
        proof = ConstructProductionProof(self.instance, self.assignment)
        other = Arithmetize(CNF.from_clauses(2, [(1,), (2,)]), self.field)
        self.assertFalse(VerifyProductionProof(other, proof, row=0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
