import random
import unittest
from dataclasses import replace

from cnf_pcp import (
    CNF,
    ConstructPCPProof,
    PCPVerifier,
    HolographicVerifier,
    PaperSearchToDecisionSAT,
    PrimeField,
    Arithmetize,
    SearchToDecisionSAT,
    build_lde,
    oracle_from_assignment,
)


class CNFPCPTests(unittest.TestCase):
    def test_dimacs_and_restrict(self):
        formula = CNF.from_dimacs(
            """c ejemplo
            p cnf 3 2
            1 -2 0
            3 0
            """
        )
        self.assertEqual(formula.num_vars, 3)
        self.assertTrue(formula.evaluate({1: True, 2: False, 3: True}))
        restricted = formula.restrict(3, False)
        self.assertEqual(restricted.clauses[-1], tuple())
        self.assertFalse(restricted.evaluate({1: True, 2: False, 3: False}))

    def test_r1cs_accepts_and_rejects(self):
        F = PrimeField()
        formula = CNF.from_clauses(3, [(1, -2), (-1, 3)])
        instance = Arithmetize(formula, F)
        good = {1: True, 2: False, 3: True}
        bad = {1: True, 2: False, 3: False}
        self.assertTrue(instance.check_witness(instance.build_witness(good)))
        self.assertFalse(instance.check_witness(instance.build_witness(bad)))

    def test_lde_interpolates_base_values(self):
        F = PrimeField()
        values = [0, 1, 4, 9, 16]
        lde = build_lde(values, F, factor=4)
        for node, value in zip(lde.base_domain, lde.base_values):
            self.assertEqual(lde.value_at(node), value)
        self.assertEqual(len(lde.extended_domain), 32)
        self.assertEqual(lde.query(0), lde.base_values[0])

    def test_pcp_rejects_corrupted_proof(self):
        F = PrimeField()
        formula = CNF.from_clauses(2, [(1,), (-2,)])
        instance = Arithmetize(formula, F)
        witness = instance.build_witness({1: True, 2: False})
        proof = ConstructPCPProof(instance, witness)
        self.assertTrue(PCPVerifier(instance, proof, r=1234567))
        incomplete = replace(proof, constraint_count=proof.constraint_count + 1)
        self.assertFalse(PCPVerifier(instance, incomplete, r=1234567))
        self.assertFalse(hasattr(proof, "truth_table_lde"))
        self.assertTrue(hasattr(proof, "witness_lde"))

        bad_witness = list(witness)
        bad_witness[1] = 0
        with self.assertRaises(ValueError):
            ConstructPCPProof(instance, bad_witness)

    def test_proof_size_is_witness_based_not_truth_table_based(self):
        formula = CNF.from_clauses(12, [(1,)])
        assignment = {variable: False for variable in range(1, 13)}
        assignment[1] = True
        instance = Arithmetize(formula, PrimeField())
        proof = ConstructPCPProof(instance, assignment)
        self.assertFalse(hasattr(proof, "truth_table_lde"))
        self.assertEqual(len(proof.witness), instance.n_vars)
        self.assertLess(len(proof.witness_lde.base_values), 1 << formula.num_vars)

    def test_holographic_transcript_queries_constant_oracles(self):
        F = PrimeField()
        formula = CNF.from_clauses(3, [(1, -2), (-1, 3)])
        instance = Arithmetize(formula, F)
        proof = ConstructPCPProof(instance, instance.build_witness({1: True, 2: False, 3: True}))
        domain_size = proof.padded_constraint_count
        bits = tuple(0 for _ in range((domain_size - 1).bit_length()))
        transcript = HolographicVerifier(instance, proof, random_bits=bits)
        self.assertTrue(transcript.accepted)
        self.assertGreater(transcript.oracle_query_count, 0)
        self.assertLessEqual(transcript.oracle_query_count, 5)
        self.assertEqual(transcript.random_bit_count, (domain_size - 1).bit_length())
        self.assertIsNotNone(transcript.query_index)
        self.assertIsNotNone(transcript.field_point)

    def test_paper_search_returns_full_transcript_and_metrics(self):
        formula = CNF.from_clauses(3, [(-1,), (-2,), (3,)])
        known = {1: False, 2: False, 3: True}
        result = PaperSearchToDecisionSAT(
            formula,
            oracle_from_assignment(known),
            rng=random.Random(19),
        )
        self.assertEqual(dict(result.assignment), known)
        self.assertTrue(formula.evaluate(result.assignment))
        self.assertEqual(result.metrics.rounds, formula.num_vars)
        self.assertGreater(result.metrics.total_random_bits, 0)
        self.assertGreater(result.metrics.total_oracle_queries, 0)
        self.assertEqual(len(result.transcripts), formula.num_vars)

    def test_search_to_decision_with_oracle(self):
        # x1=0, x2=0 y x3=1 es una asignación satisfactoria.
        formula = CNF.from_clauses(3, [(-1,), (-2,), (3,)])
        known = {1: False, 2: False, 3: True}
        result = SearchToDecisionSAT(
            formula,
            oracle_from_assignment(known),
            rng=random.Random(11),
        )
        self.assertEqual(result, known)
        self.assertTrue(formula.evaluate(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
