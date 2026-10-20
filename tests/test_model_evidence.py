import unittest

from zhidian.provider import run_agent, total_usage, usage_summary


class ModelEvidenceTests(unittest.TestCase):
    def test_final_text_excludes_unverified_planning_and_audits_each_model(self):
        replies = iter([
            {"id": "call-a", "model": "provider-a/free", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "cost": 0.2}, "output": [{"type": "message", "content": [{"type": "output_text", "text": "尚未验证的中间断言：已修复。"}]}, {"type": "function_call", "name": "inspect_contract", "arguments": "{}", "call_id": "tool-1"}]},
            {"id": "call-b", "model": "provider-b/free", "usage": {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23, "cost": 0.3}, "output": [{"type": "message", "content": [{"type": "output_text", "text": "目前只有规格证据，修复尚未验证。"}]}]},
        ])
        result = run_agent({"model": "free-router"}, {}, lambda *args: {"verified": False}, lambda *args: None, request_fn=lambda *args: next(replies))
        self.assertEqual(result["text"], "目前只有规格证据，修复尚未验证。")
        self.assertEqual([row["actual_model"] for row in result["requests"]], ["provider-a/free", "provider-b/free"])
        self.assertEqual(result["requests"][0]["tool_names"], ["inspect_contract"])
        self.assertEqual(result["usage"]["reported_cost"], 0.5)
        self.assertEqual(result["usage"]["total_tokens"], 35)

    def test_empty_terminal_response_cannot_reuse_an_earlier_claim(self):
        replies = iter([
            {"output": [{"type": "message", "content": [{"type": "output_text", "text": "计划阶段已通过。"}]}, {"type": "function_call", "name": "inspect_contract", "arguments": "{}", "call_id": "tool-1"}]},
            {"output": []},
        ])
        with self.assertRaisesRegex(RuntimeError, "未给出教学解释"):
            run_agent({"model": "test"}, {}, lambda *args: {}, lambda *args: None, request_fn=lambda *args: next(replies))

    def test_missing_or_malformed_usage_is_unknown_instead_of_zero(self):
        for value in [{}, None, {"cost": float("nan")}, {"cost": -1}, {"cost": True}]:
            self.assertIsNone(usage_summary(value)["reported_cost"])
        complete = {"usage": usage_summary({"cost": 0, "total_tokens": 1})}
        missing = {"usage": usage_summary({})}
        result = total_usage([complete, missing])
        self.assertIsNone(result["reported_cost"])
        self.assertFalse(result["reported_cost_complete"])
        self.assertIsNone(result["total_tokens"])

    def test_metadata_never_echoes_a_configured_credential(self):
        response = {"id": "secret-key", "model": "echo-secret-key", "output": [{"type": "message", "content": [{"type": "output_text", "text": "结果。"}]}]}
        events = []
        result = run_agent({"model": "test", "key": "secret-key"}, {}, lambda *args: {}, lambda *args: events.append(args), request_fn=lambda *args: response)
        self.assertNotIn("secret-key", str(result))
        self.assertNotIn("secret-key", str(events))
