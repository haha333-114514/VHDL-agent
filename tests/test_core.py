from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from zhidian.catalog import TASKS, vectors
from zhidian.mutations import range_overfit_fir
from zhidian.provider import Configuration, run_agent
from zhidian.provider import run_agent as real_model_loop
from zhidian.service import Service
from zhidian.simulator import find_ghdl, simulate, validate_source


@unittest.skipUnless(find_ghdl(), "GHDL is required for actual simulation integration tests")
class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zhidian-tests-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_reference_circuits_pass_and_teaching_bugs_fail(self):
        expected_counts = {"counter": 103, "majority": 32, "sequence": 73, "fir": 50}
        for task_id, task in TASKS.items():
            with self.subTest(task=task_id):
                wrong = simulate(task_id, task["starter"], "full", self.root / (task_id + "-wrong"))
                correct = simulate(task_id, task["solution"], "full", self.root / (task_id + "-correct"))
                self.assertTrue(wrong["compiled"], wrong["log"])
                self.assertTrue(wrong["completed"], wrong["log"])
                self.assertFalse(wrong["passed"])
                self.assertGreater(wrong["failed"], 0)
                self.assertTrue(correct["passed"], correct["log"])
                self.assertEqual(correct["total"], expected_counts.get(task_id,len(vectors(task_id,"full"))))
                self.assertTrue(Path(correct["wave_file"]).is_file())
                self.assertNotEqual(wrong["source_hash"], correct["source_hash"])

    def test_basic_checks_can_miss_the_known_boundary_bugs(self):
        for task_id, task in TASKS.items():
            with self.subTest(task=task_id):
                result = simulate(task_id, task["starter"], "smoke", self.root / task_id)
                self.assertTrue(result["passed"], result["log"])

    def test_compile_failure_is_not_reported_as_a_functional_pass(self):
        source = TASKS["counter"]["solution"].replace("count <= count + 1;", "count <= count + ;")
        result = simulate("counter", source, "full", self.root / "compile")
        self.assertFalse(result["compiled"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["total"], 0)
        self.assertTrue(result["diagnostics"])

    def test_runtime_failure_cannot_be_misread_as_a_completed_test(self):
        source = TASKS["counter"]["solution"].replace("if rising_edge(clk) then", 'if rising_edge(clk) then\n      assert false report "intentional test failure" severity failure;')
        result = simulate("counter", source, "full", self.root / "runtime")
        self.assertTrue(result["compiled"], result["log"])
        self.assertFalse(result["completed"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "runtime_error")

    def test_missing_tool_never_produces_fake_simulation(self):
        with patch("zhidian.simulator.find_ghdl", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "GHDL"):
                simulate("counter", TASKS["counter"]["solution"], "full", self.root / "missing")

    def test_counter_does_not_require_defined_output_before_first_reset_edge(self):
        source = TASKS["counter"]["solution"].replace(" := (others => '0')", "")
        result = simulate("counter", source, "full", self.root / "uninitialized")
        self.assertTrue(result["passed"], result["log"])
        self.assertEqual(result["checks"][0]["case"], "reset")

    def test_file_driven_testbench_writes_observed_simulation_values(self):
        folder = self.root / "file-io"
        result = simulate("file_rom",TASKS["file_rom"]["solution"],"full",folder)
        self.assertTrue(result["passed"],result["log"])
        input_rows = [list(map(int,line.split())) for line in (folder/"vectors.txt").read_text().splitlines()]
        output_rows = [list(map(int,line.split())) for line in (folder/"observed.txt").read_text().splitlines()]
        self.assertEqual(len(output_rows),32)
        self.assertEqual([(a,expected) for a,actual,expected in output_rows],[tuple(row) for row in input_rows])
        self.assertTrue(all(actual == expected for _,actual,expected in output_rows))


class ValidationTests(unittest.TestCase):
    def test_files_foreign_bindings_and_reserved_testbench_names_are_rejected(self):
        source = TASKS["counter"]["starter"]
        for addition in ["file secret : text;", "attribute foreign of x : signal is \"VHPIDIRECT x\";", "use std.env.all;", "entity zd_tb is end;", "library malicious;"]:
            with self.subTest(addition=addition):
                with self.assertRaises(ValueError):
                    validate_source("counter", source + "\n" + addition)

    def test_current_interface_is_required(self):
        with self.assertRaises(ValueError):
            validate_source("counter", TASKS["fir"]["starter"])

    def test_reference_vectors_cover_boundary_semantics(self):
        majority = vectors("majority", "full")
        self.assertEqual(len(majority), 32)
        self.assertEqual(sum(row["expected"] for row in majority), 16)
        counter = vectors("counter", "full")
        self.assertTrue(any(row["reset"] == row["en"] == 1 and row["expected"] == 0 for row in counter))
        impulse = vectors("fir", "boundary")[1:5]
        self.assertEqual([row["expected"] for row in impulse], [1, 2, -1, 0])


class ModelLoopTests(unittest.TestCase):
    def test_real_tool_call_protocol_is_completed_with_evidence(self):
        requests = []
        dispatched = []
        def request(config, messages, schemas):
            requests.append(json.loads(json.dumps(messages)))
            self.assertEqual(schemas[0]["type"], "function")
            if len(requests) == 1:
                return {"output": [{"type": "function_call", "name": "inspect_contract", "arguments": "{}", "call_id": "call-1", "id": "fc-1"}]}
            self.assertTrue(any(row.get("type") == "function_call_output" and row["call_id"] == "call-1" for row in messages))
            return {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "请对照工具中的复位优先级约束。"}]}]}
        def dispatch(name, args):
            dispatched.append((name, args))
            return {"requirements": ["reset wins"]}
        result = run_agent({"model": "test-model"}, {"source": "student code"}, dispatch, lambda *args: None, request_fn=request)
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(dispatched, [("inspect_contract", {})])
        self.assertIn("复位", result["text"])

    def test_invalid_arguments_are_returned_to_the_model_as_tool_errors(self):
        responses = iter([
            {"output": [{"type": "function_call", "name": "inspect_contract", "arguments": "[]", "call_id": "bad"}]},
            {"output": [{"type": "message", "content": [{"type": "output_text", "text": "参数无效，不能据此判断。"}]}]},
        ])
        dispatched = []
        result = run_agent({"model": "test"}, {}, lambda *args: dispatched.append(args), lambda *args: None, request_fn=lambda *args: next(responses))
        self.assertEqual(dispatched, [])
        self.assertEqual(result["tool_calls"], 1)

    def test_tool_budget_stops_unbounded_loops(self):
        def request(*args):
            return {"output": [{"type": "function_call", "name": "inspect_contract", "arguments": "{}", "call_id": str(index)} for index in range(3)]}
        with self.assertRaisesRegex(RuntimeError, "8"):
            run_agent({"model": "test"}, {}, lambda *args: {}, lambda *args: None, request_fn=request)

    def test_last_tool_round_is_followed_by_one_summary_without_tools(self):
        count = 0
        def request(config, messages, schemas):
            nonlocal count
            count += 1
            if count <= 6:
                self.assertTrue(schemas)
                return {"output": [{"type": "function_call", "name": "inspect_contract", "arguments": "{}", "call_id": str(count)}]}
            self.assertEqual(schemas, [])
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "仅归纳已有证据。"}]}]}
        result = run_agent({"model": "test"}, {}, lambda *args: {}, lambda *args: None, request_fn=request)
        self.assertEqual(result["rounds"], 7)
        self.assertEqual(result["tool_calls"], 6)

    def test_summary_round_cannot_execute_a_requested_tool(self):
        calls = []
        def request(config, messages, schemas):
            return {"output": [{"type": "function_call", "name": "inspect_contract", "arguments": "{}", "call_id": str(len(calls))}]}
        with self.assertRaisesRegex(RuntimeError, "收尾"):
            run_agent({"model": "test"}, {}, lambda *args: calls.append(args), lambda *args: None, request_fn=request)
        self.assertEqual(len(calls), 6)

    def test_configuration_does_not_expose_keys_or_allow_remote_plain_http(self):
        config = Configuration()
        public = config.update({"base": "https://api.openai.com/v1", "model": "test", "key": "test-secret-123"})
        self.assertNotIn("test-secret-123", json.dumps(public))
        self.assertTrue(public["configured"])
        public = config.update({"base": "http://127.0.0.1:1234/v1", "model": "local-test"})
        self.assertFalse(public["has_key"], "changing destinations must not reuse the previous credential")
        with self.assertRaises(ValueError):
            config.update({"base": "http://example.com/v1", "model": "test"})
        with self.assertRaises(ValueError):
            config.update({"base": "https://user:pass@example.com/v1", "model": "test"})


@unittest.skipUnless(find_ghdl(), "GHDL required for candidate verification")
class ModelServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zhidian-model-test-")
        self.service = Service(Path(self.temporary.name))
        self.service.config.update({"base": "https://api.openai.com/v1", "model": "test-model", "key": "unit-test-secret"})

    def tearDown(self):
        self.temporary.cleanup()

    def wait(self, run_id):
        start = time.monotonic()
        while time.monotonic() - start < 30:
            job = self.service.get(run_id)
            if job["status"] != "running":
                self.assertEqual(job["status"], "complete", job)
                return job
            time.sleep(0.1)
        self.fail("model test did not complete")

    def test_candidate_patch_is_really_simulated_without_changing_original(self):
        requests = []
        def request(config, messages, schemas):
            requests.append(messages)
            if len(requests) == 1:
                return {"output": [
                    {"type": "function_call", "name": "read_waveform", "arguments": '{"center_index":14}', "call_id": "wave-1"},
                    {"type": "function_call", "name": "propose_patch", "arguments": json.dumps({"source": TASKS["counter"]["solution"], "explanation": "把复位置于使能之前。"}), "call_id": "patch-1"},
                ]}
            patch_output = next(row for row in messages if row.get("call_id") == "patch-1" and row.get("type") == "function_call_output")
            self.assertEqual(json.loads(patch_output["output"])["status"], "passed")
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "候选版本已由工具完成验证。"}]}]}
        def adapter(config, context, dispatch, event):
            return real_model_loop(config, context, dispatch, event, request_fn=request)
        with patch("zhidian.service.run_agent", side_effect=adapter):
            run = self.service.start({"task_id": "counter", "source": TASKS["counter"]["starter"], "mode": "model"})
            job = self.wait(run["id"])
        self.assertIsNone(job["model_error"])
        self.assertFalse(job["result"]["passed"])
        self.assertTrue(job["candidate"]["verified"])
        self.assertEqual(job["candidate"]["result"]["total"], 103)
        self.assertEqual(len(job["candidate"]["challenges"]), 2)
        self.assertTrue(all(row["passed"] for row in job["candidate"]["challenges"]))
        self.assertIn("追加验证 2", self.service.report(job))
        self.assertTrue(job["candidate"]["challenges"][0]["wave_url"].endswith("wave.vcd"))
        self.assertEqual(job["source"], TASKS["counter"]["starter"])
        self.assertNotIn("unit-test-secret", json.dumps(job))
        snapshot = (Path(self.temporary.name) / "runs" / run["id"] / "run.json").read_text(encoding="utf-8")
        self.assertNotIn("unit-test-secret", snapshot)

    def test_public_test_pass_does_not_mark_an_overfit_model_patch_verified(self):
        def adapter(config, context, dispatch, event):
            output = dispatch("propose_patch", {"source": range_overfit_fir(), "explanation": "受控过拟合候选，仅用于工程验证。"})
            self.assertTrue(output["public_tests_passed"])
            self.assertFalse(output["verified"])
            self.assertEqual(output["status"], "failed")
            self.assertTrue(all(row["failed"] > 0 for row in output["challenges"]))
            return {"text": "公开测试通过，但追加验证失败，不能称已修复。", "rounds": 1, "tool_calls": 1, "model": "offline-test"}
        with patch("zhidian.service.run_agent", side_effect=adapter):
            run = self.service.start({"task_id": "fir", "source": TASKS["fir"]["starter"], "mode": "model"})
            job = self.wait(run["id"])
        self.assertFalse(job["candidate"]["verified"])
        self.assertTrue(job["candidate"]["result"]["passed"])
        self.assertIn("综合判定：尚未通过", self.service.report(job))
        self.assertEqual(job["source"], TASKS["fir"]["starter"])

    def test_model_failure_preserves_simulation_and_redacts_key(self):
        with patch("zhidian.service.run_agent", side_effect=RuntimeError("failed unit-test-secret")):
            run = self.service.start({"task_id": "counter", "source": TASKS["counter"]["starter"], "mode": "model"})
            job = self.wait(run["id"])
        self.assertEqual(job["result"]["total"], 103)
        self.assertIn("已隐藏", job["model_error"])
        self.assertNotIn("unit-test-secret", json.dumps(job))


if __name__ == "__main__":
    unittest.main()
