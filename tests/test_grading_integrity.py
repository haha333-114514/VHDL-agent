import tempfile
from pathlib import Path
import unittest

from tools.audit_grading import grading_cases
from zhidian.grading import expected_checks, grade_log
from zhidian.simulator import diagnose, find_ghdl, simulate


class GradingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.manifest = [{"index": 1, "time_ns": 6, "case": "reset", "expected": 0, "inputs": "reset=1"}]
        self.line = "ZD_CHECK|test-tag|1|6|reset|0|0|reset=1\n"
        self.ending = "ZD_DONE|test-tag|1|0\n"

    def test_expected_counts_match_the_fixed_contracts(self):
        expected = {"counter": 103, "majority": 32, "sequence": 73, "fir": 50, "signed_add": 73, "adder_tree": 48, "file_rom": 32, "lut": 16, "ram": 42, "pipeline": 35, "serial_mul": 134}
        for task, count in expected.items():
            self.assertEqual(len(expected_checks(task, "full")), count)
        self.assertEqual(len(expected_checks("counter", "challenge", 123)), 247)

    def test_only_a_complete_tagged_manifest_passes(self):
        result = grade_log(self.line+self.ending, "test-tag", self.manifest, 0)
        self.assertTrue(result["passed"])
        self.assertEqual(result["expected_total"], 1)

    def test_untagged_or_wrong_tag_reports_do_not_count(self):
        for log in ["ZD_DONE|0|0\n", self.line.replace("test-tag", "other")+self.ending.replace("test-tag", "other")]:
            with self.subTest(log=log):
                result = grade_log(log, "test-tag", self.manifest, 0)
                self.assertFalse(result["completed"])
                self.assertEqual(result["total"], 0)

    def test_log_cannot_replace_golden_values_or_sampling_metadata(self):
        for altered in [self.line.replace("|0|0|", "|1|1|"), self.line.replace("|1|6|", "|2|6|"), self.line.replace("|1|6|", "|1|7|"), self.line.replace("reset=1", "reset=0")]:
            with self.subTest(log=altered):
                result = grade_log(altered+self.ending, "test-tag", self.manifest, 0)
                self.assertFalse(result["completed"])
                self.assertIsNotNone(result["integrity_error"])

    def test_nonbinary_output_is_not_numeric_zero(self):
        result = grade_log("ZD_INVALID|test-tag|1\n"+self.line+"ZD_DONE|test-tag|1|1\n", "test-tag", self.manifest, 0)
        self.assertTrue(result["completed"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["invalid_count"], 1)
        self.assertIsNone(result["checks"][0]["actual"])

    def test_zero_expected_checks_duplicates_and_guard_exit_cannot_pass(self):
        examples = [
            ("ZD_DONE|test-tag|0|0\n", []),
            (self.line+self.ending+self.ending, self.manifest),
            ("ZD_INVALID|test-tag|1\nZD_INVALID|test-tag|1\n"+self.line+self.ending, self.manifest),
            (self.line+self.ending+"simulation stopped @0ms by --stop-delta=1000", self.manifest),
        ]
        for log, manifest in examples:
            with self.subTest(log=log):
                self.assertFalse(grade_log(log, "test-tag", manifest, 0)["completed"])


@unittest.skipUnless(find_ghdl(), "GHDL required")
class RealGradingBoundaryTests(unittest.TestCase):
    def test_real_boundary_cases_and_diagnosis(self):
        with tempfile.TemporaryDirectory(prefix="zhidian-integrity-") as directory:
            for case in grading_cases():
                with self.subTest(case=case["id"]):
                    result = simulate(case["task_id"], case["source"], "full", Path(directory)/case["id"])
                    self.assertEqual(result["passed"], case["expected_pass"], result["log"])
                    if case["id"] == "unknown_zero":
                        self.assertGreater(result["invalid_count"], 0)
                        self.assertEqual(diagnose("counter", case["source"], result)["kind"], "undefined_output")
                    elif case["id"] == "forged_completion":
                        self.assertFalse(result["completed"])
                        self.assertEqual(result["expected_total"], 103)
                        self.assertEqual(result["status"], "limit")
