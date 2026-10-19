from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import make_handler
from zhidian.catalog import TASKS
from zhidian.service import Service
from zhidian.simulator import find_ghdl


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="zhidian-http-")
        cls.service = Service(Path(cls.temporary.name))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.service))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.csrf = cls.request("/api/health")[1]["csrf"]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    @classmethod
    def request(cls, path, body=None, headers=None):
        request_headers = {"Content-Type": "application/json", "X-Zhidian-Token": getattr(cls, "csrf", "")}
        request_headers.update(headers or {})
        request = Request(cls.base + path, data=None if body is None else json.dumps(body).encode(), headers=request_headers)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            content = json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw.decode("utf-8", errors="replace")
            return response.status, content

    def test_static_app_and_public_contract_do_not_reveal_quiz_answers(self):
        code, page = self.request("/")
        self.assertEqual(code, 200)
        self.assertIn("知电", page)
        code, data = self.request("/api/tasks")
        self.assertEqual(len(data["tasks"]), 11)
        self.assertNotIn("solution", data["tasks"][0])
        code, data = self.request("/api/quizzes")
        self.assertEqual(len(data["quizzes"]), 22)
        self.assertNotIn("answer", data["quizzes"][0])

    def test_mutations_require_local_origin_and_csrf(self):
        code, _ = self.request("/api/quiz", {"quiz_id": "counter_priority", "choice": 1}, {"X-Zhidian-Token": "wrong"})
        self.assertEqual(code, 403)
        code, _ = self.request("/api/config", {}, {"Origin": "https://evil.invalid"})
        self.assertEqual(code, 403)
        code, _ = self.request("/api/health", headers={"Host": "evil.invalid"})
        self.assertEqual(code, 403)

    def test_static_path_traversal_is_rejected(self):
        code, _ = self.request("/%2e%2e/server.py")
        self.assertEqual(code, 404)

    def test_free_model_configuration_round_trip_does_not_expose_credentials(self):
        original = self.service.config.snapshot()
        try:
            code, data = self.request("/api/config", {"base": "https://openrouter.ai/api/v1", "model": "openrouter/free", "protocol": "chat_completions", "key": "http-test-key"})
            self.assertEqual(code, 200)
            self.assertTrue(data["configured"])
            self.assertEqual(data["protocol"], "chat_completions")
            self.assertNotIn("http-test-key", json.dumps(data))
            self.assertEqual(self.request("/api/health")[1]["provider"]["model"], "openrouter/free")
            self.assertIn("OpenRouter · 免费模型", self.request("/")[1])
        finally:
            self.service.config.update({**original, "clear_key": not original["key"]})

    def test_invalid_user_inputs_have_clear_errors(self):
        code, data = self.request("/api/run", {"task_id": "missing", "source": "entity a is end;"})
        self.assertEqual(code, 400)
        self.assertIn("error", data)
        code, _ = self.request("/api/quiz", {"quiz_id": "counter_priority", "choice": True})
        self.assertEqual(code, 400)

    @unittest.skipUnless(find_ghdl(), "GHDL required")
    def test_full_experiment_report_reference_and_learning_records(self):
        def wait(run_id):
            start = time.monotonic()
            while time.monotonic() - start < 30:
                code, job = self.request("/api/runs/" + run_id)
                if job["status"] != "running":
                    self.assertEqual(job["status"], "complete", job)
                    return job
                time.sleep(0.12)
            self.fail("experiment did not finish")
        code, result = self.request("/api/run", {"task_id": "counter", "source": TASKS["counter"]["starter"]})
        self.assertEqual(code, 202)
        job = wait(result["id"])
        self.assertTrue(job["smoke"]["passed"])
        self.assertEqual(job["result"]["total"], 103)
        self.assertFalse(job["result"]["passed"])
        self.assertEqual(job["diagnosis"]["kind"], "priority")
        self.assertNotIn("wave_file", job["result"])
        self.assertTrue(job["result"]["wave_url"].startswith("/api/runs/"))
        code, report = self.request(f"/api/runs/{job['id']}/report")
        self.assertEqual(code, 200)
        self.assertIn("源码 SHA-256", report)
        self.assertIn("ZD_CHECK", report)
        code, hint = self.request("/api/hint", {"run_id": job["id"], "level": 1})
        self.assertEqual(code, 200)
        self.assertIn("reset", hint["text"])
        code, wave = self.request(job["result"]["wave_url"])
        self.assertEqual(code, 200)
        self.assertIn("$timescale", wave)
        code, _ = self.request(f"/api/runs/{job['id']}/artifact/%2e%2e/%2e%2e/learning.sqlite3")
        self.assertEqual(code, 404)
        code, reference = self.request("/api/run", {"task_id": "counter", "source": TASKS["counter"]["starter"], "action": "reference"})
        fixed = wait(reference["id"])
        self.assertTrue(fixed["result"]["passed"])
        self.assertTrue(fixed["reference_run"])
        code, quiz = self.request("/api/quiz", {"quiz_id": "counter_priority", "choice": 1})
        self.assertTrue(quiz["correct"])
        code, profile = self.request("/api/profile")
        self.assertEqual(profile["passed_runs"], 0, "reference runs must not count as student successes")
        self.assertGreaterEqual(profile["quiz_correct"], 1)
        reloaded = Service(Path(self.temporary.name))
        restored = reloaded.get(job["id"])
        self.assertEqual(restored["result"]["total"], 103)
        self.assertEqual(len(reloaded.store.history()), 2)


if __name__ == "__main__":
    unittest.main()
