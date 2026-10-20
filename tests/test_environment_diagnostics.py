from contextlib import redirect_stdout
import io
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from tools import evaluate_innovations
from zhidian.provider import request_response
from zhidian.simulator import diagnose


class EnvironmentDiagnosticsTests(unittest.TestCase):
    def test_standard_library_timestamp_error_is_not_a_student_logic_error(self):
        result = {"compiled": False, "log": 'entity "counter4" is obsoleted by package "std_logic_1164"', "diagnostics": []}
        self.assertEqual(diagnose("counter", "", result)["kind"], "environment")

    def test_certificate_error_explains_time_and_certificate_checks(self):
        failure = URLError(ssl.SSLCertVerificationError(1, "certificate not yet valid"))
        with patch("zhidian.provider.build_opener") as factory:
            factory.return_value.open.side_effect = failure
            with self.assertRaisesRegex(RuntimeError, "系统日期时间"):
                request_response({"base": "https://example.invalid/v1", "model": "test", "key": ""}, [], [])

    def test_failed_evaluation_never_overwrites_a_successful_report(self):
        result = {"compiled": False, "completed": False, "passed": False, "total": 0, "failed": 0, "checks": [], "source_hash": "test", "testbench_hash": "test", "seed": None}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"docs").mkdir()
            for suffix in ("md", "json"):
                (root/"docs"/f"创新实验结果.{suffix}").write_text("known successful report", encoding="utf-8")
            with patch.object(evaluate_innovations, "ROOT", root), patch.object(evaluate_innovations, "simulate", return_value=result), redirect_stdout(io.StringIO()):
                self.assertEqual(evaluate_innovations.main(), 1)
            for suffix in ("md", "json"):
                self.assertEqual((root/"docs"/f"创新实验结果.{suffix}").read_text(encoding="utf-8"), "known successful report")
