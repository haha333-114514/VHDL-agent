import hashlib
from pathlib import Path
import tempfile
import unittest

from zhidian.catalog import TASKS, vectors
from zhidian.extended_catalog import fixture_files
from zhidian.mutations import mutation_cases, range_overfit_fir
from zhidian.simulator import find_ghdl, simulate
from zhidian.verification import verify_candidate


class ChallengeVectorTests(unittest.TestCase):
    def test_challenges_replay_and_change_sequences_without_changing_contract(self):
        for task_id in TASKS:
            with self.subTest(task=task_id):
                one = vectors(task_id, "challenge", seed=31)
                self.assertEqual(one, vectors(task_id, "challenge", seed=31))
                self.assertNotEqual(one, vectors(task_id, "challenge", seed=32))
                if task_id == "majority":
                    self.assertEqual({row["din"] for row in one}, set(range(32)))
                if task_id == "lut":
                    self.assertEqual({row["din"] for row in one}, set(range(16)))
                if task_id == "file_rom":
                    text = fixture_files(task_id, "challenge", seed=31)["vectors.txt"]
                    self.assertEqual([int(line.split()[0]) for line in text.splitlines()], [row["addr"] for row in one])
        with self.assertRaises(ValueError):
            vectors("counter", "challenge")

    def test_mutations_are_finite_distinct_and_change_reference_sources(self):
        cases = mutation_cases()
        self.assertEqual(len(cases), 15)
        self.assertEqual(len({case["id"] for case in cases}), 15)
        for case in cases:
            self.assertNotEqual(case["source"], TASKS[case["task_id"]]["solution"])


@unittest.skipUnless(find_ghdl(), "GHDL required")
class HeldOutVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zhidian-challenge-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_public_test_overfit_is_rejected_by_both_additional_suites(self):
        checked = verify_candidate("fir", range_overfit_fir(), self.root / "overfit", seeds=(11, 22))
        self.assertTrue(checked["result"]["passed"])
        self.assertFalse(checked["verified"])
        self.assertEqual(len(checked["challenges"]), 2)
        self.assertTrue(all(row["completed"] and not row["passed"] for row in checked["challenges"]))
        correct = verify_candidate("fir", TASKS["fir"]["solution"], self.root / "correct", seeds=(11, 22))
        self.assertTrue(correct["verified"])
        for index, row in enumerate(correct["challenges"], 1):
            bench = self.root / "correct" / f"challenge-{index}" / "zd_tb.vhd"
            self.assertEqual(hashlib.sha256(bench.read_bytes()).hexdigest(), row["testbench_hash"])

    def test_all_reference_designs_pass_challenges(self):
        for task_id, task in TASKS.items():
            with self.subTest(task=task_id):
                result = simulate(task_id, task["solution"], "challenge", self.root / task_id, seed=20261019)
                self.assertTrue(result["passed"], result["log"])

    def test_public_failure_does_not_claim_a_challenge_was_run(self):
        checked = verify_candidate("counter", TASKS["counter"]["starter"], self.root / "incorrect")
        self.assertFalse(checked["verified"])
        self.assertEqual(checked["challenges"], [])
