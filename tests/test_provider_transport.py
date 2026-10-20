from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from zhidian.provider import Configuration, load_env, request_response, run_agent, tools_schema


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.replies = []
        requests = self.requests
        replies = self.replies
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                if self.path.startswith("/redirect/"):
                    self.send_response(302)
                    self.send_header("Location", "/unexpected")
                    self.end_headers()
                    return
                status, data = replies.pop(0) if replies else (200, {"output": [{"type": "message", "content": [{"type": "output_text", "text": "transport test"}]}]})
                response = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_responses_payload_and_authorization_use_the_configured_destination(self):
        result = request_response({"base": self.base + "/v1", "model": "test-model", "key": "test-only-key"}, [{"role": "user", "content": "test"}], tools_schema())
        self.assertEqual(result["output"][0]["type"], "message")
        sent = self.requests[0]
        self.assertEqual(sent["path"], "/v1/responses")
        self.assertEqual(sent["auth"], "Bearer test-only-key")
        self.assertFalse(sent["body"]["store"])
        self.assertEqual(sent["body"]["model"], "test-model")
        self.assertEqual(len(sent["body"]["tools"]), 5)

    def test_redirect_does_not_forward_an_authorization_header(self):
        with self.assertRaisesRegex(RuntimeError, "302"):
            request_response({"base": self.base + "/redirect", "model": "test-model", "key": "test-only-key"}, [], [])
        self.assertEqual(len(self.requests), 1)

    def test_chat_completion_tool_round_trip_preserves_ids_and_reasoning_signatures(self):
        self.replies.extend([
            (200, {"model": "test/free-model:free", "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque-signature"}], "tool_calls": [
                {"id": "contract-1", "type": "function", "function": {"name": "inspect_contract", "arguments": "{}"}},
                {"id": "wave-2", "type": "function", "function": {"name": "read_waveform", "arguments": '{"center_index": 13}'}},
            ]}}]}),
            (200, {"model": "test/free-model:free", "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "检查点13显示复位应优先。"}}]}),
        ])
        dispatched = []
        def dispatch(name, args):
            dispatched.append((name, args))
            return {"evidence": "reset wins", "index": args.get("center_index")}
        config = {"base": self.base + "/v1", "model": "openrouter/free", "key": "test-only-key", "protocol": "chat_completions"}
        result = run_agent(config, {"student_source": "test VHDL"}, dispatch, lambda *args: None)
        self.assertEqual(result["tool_calls"], 2)
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(result["model"], "test/free-model:free")
        self.assertEqual(result["requested_model"], "openrouter/free")
        self.assertNotIn("opaque-signature", result["text"])
        self.assertEqual(dispatched, [("inspect_contract", {}), ("read_waveform", {"center_index": 13})])
        self.assertEqual([row["path"] for row in self.requests], ["/v1/chat/completions"] * 2)
        first, second = [row["body"] for row in self.requests]
        self.assertEqual(first["model"], "openrouter/free")
        self.assertNotIn("models", first, "no fallback model may be added")
        self.assertNotIn("include", first)
        self.assertNotIn("instructions", first)
        self.assertEqual(first["tools"][0]["function"]["name"], "inspect_contract")
        self.assertNotIn("strict", first["tools"][0]["function"])
        self.assertEqual(second["messages"][2]["reasoning_details"][0]["data"], "opaque-signature")
        returned = second["messages"][3:]
        self.assertEqual([row["tool_call_id"] for row in returned], ["contract-1", "wave-2"])
        self.assertEqual(json.loads(returned[1]["content"])["index"], 13)

    def test_free_quota_error_does_not_retry_a_paid_model(self):
        self.replies.append((429, {"error": {"message": "quota exceeded"}}))
        config = {"base": self.base, "model": "openrouter/free", "key": "test", "protocol": "chat_completions"}
        with self.assertRaisesRegex(RuntimeError, "不会自动切换付费"):
            run_agent(config, {}, lambda *args: self.fail("must not dispatch"), lambda *args: None)
        self.assertEqual(len(self.requests), 1)

    def test_chat_transport_preserves_reported_identity_and_usage(self):
        self.replies.append((200, {"id": "generation-123", "model": "provider/free-model", "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15, "cost": 0}, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "已返回。"}}]}))
        result = run_agent({"base": self.base, "model": "openrouter/free", "key": "test", "protocol": "chat_completions"}, {}, lambda *args: {}, lambda *args: None)
        self.assertEqual(result["requests"][0]["response_id"], "generation-123")
        self.assertEqual(result["requests"][0]["actual_model"], "provider/free-model")
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertEqual(result["usage"]["reported_cost"], 0)

    def test_incomplete_or_malformed_chat_outputs_do_not_execute_tools(self):
        for choice in [
            {"finish_reason": "length", "message": {"content": "partial"}},
            {"finish_reason": "tool_calls", "message": {"tool_calls": [{"type": "function", "function": {"name": "inspect_contract", "arguments": "{}"}}]}},
            {"finish_reason": "stop", "message": {"content": {"invalid": True}}},
        ]:
            with self.subTest(choice=choice):
                self.replies.append((200, {"choices": [choice]}))
                with self.assertRaises(RuntimeError):
                    run_agent({"base": self.base, "model": "test", "key": "", "protocol": "chat_completions"}, {}, lambda *args: self.fail("must not dispatch"), lambda *args: None)

    def test_chat_redirects_are_not_followed(self):
        with self.assertRaisesRegex(RuntimeError, "302"):
            request_response({"base": self.base + "/redirect", "model": "test", "key": "test", "protocol": "chat_completions"}, [], tools_schema())
        self.assertEqual(len(self.requests), 1)


class FreeConfigurationTests(unittest.TestCase):
    def test_defaults_offer_free_router_without_a_key(self):
        with patch.dict(os.environ, {}, clear=True):
            config = Configuration()
        public = config.public()
        self.assertEqual(public["base"], "https://openrouter.ai/api/v1")
        self.assertEqual(public["model"], "openrouter/free")
        self.assertEqual(public["protocol"], "chat_completions")
        self.assertFalse(public["configured"])
        with self.assertRaises(ValueError):
            config.update({"base": public["base"], "model": "test", "protocol": "invalid"})

    def test_new_destination_does_not_reuse_a_legacy_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-secret", "MODEL_BASE_URL": "https://openrouter.ai/api/v1"}, clear=True):
            self.assertFalse(Configuration().public()["has_key"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-secret", "OPENAI_MODEL": "legacy-model"}, clear=True):
            config = Configuration().snapshot()
            self.assertEqual(config["base"], "https://api.openai.com/v1")
            self.assertEqual(config["protocol"], "responses")

    def test_dotenv_loads_neutral_settings_and_respects_existing_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"MODEL_API_KEY": "process-key"}, clear=True):
            file = Path(directory) / ".env"
            file.write_text('MODEL_BASE_URL=https://openrouter.ai/api/v1\nMODEL_NAME=openrouter/free\nMODEL_PROTOCOL=chat_completions\nMODEL_API_KEY=file-key\n', encoding="utf-8")
            load_env(file)
            config = Configuration()
            self.assertEqual(config.snapshot()["key"], "process-key")
            self.assertTrue(config.public()["configured"])
            self.assertNotIn("process-key", json.dumps(config.public()))
