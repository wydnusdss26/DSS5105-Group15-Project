import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from agent import Copilot, TOOLS
from factory import Factory
from openai_client import MODEL, ENDPOINT, ModelError, api_key, complete, network_enabled
from state import Store


def http_response(output, **extra):
    return io.BytesIO(json.dumps({"status": "completed", "output": output,
                                "usage": {"input_tokens": 12, "output_tokens": 5}, **extra}).encode())


def final_message(summary="34 orders"):
    return {"type": "message", "id": "msg_fixture", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps({"kind": "answer", "summary": summary,
                          "evidence_ids": ["E1"]}), "annotations": []}]}


class OpenAIClientTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_NETWORK_ENABLED": "true", "OPENAI_API_KEY": "fixture-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_exact_model_endpoint_and_request_contract(self):
        with patch("openai_client.urllib.request.urlopen", return_value=http_response([final_message()])) as http:
            message, usage = complete([{"role": "system", "content": "Return JSON."},
                                       {"role": "user", "content": "Count orders."}], TOOLS)
        request = http.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(payload["model"], "gpt-6.1-sol")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertEqual(payload["text"]["format"]["type"], "json_object")
        self.assertNotIn("thinking", payload)
        self.assertNotIn("messages", payload)
        self.assertEqual(len(payload["tools"]), 8)
        self.assertFalse(payload["tools"][0]["strict"])
        self.assertEqual(payload["input"][0]["role"], "developer")
        self.assertNotIn("fixture-key", json.dumps(payload))
        self.assertEqual(usage, {"prompt_tokens": 12, "completion_tokens": 5})
        self.assertIn("34 orders", message["content"])

    def test_reasoning_and_call_ids_survive_tool_rounds(self):
        reasoning = {"type": "reasoning", "id": "rs_fixture", "summary": [], "encrypted_content": "encrypted-fixture"}
        call = {"type": "function_call", "id": "fc_fixture", "call_id": "call_fixture",
                "name": "query_orders", "arguments": '{"status":"IN_PROGRESS"}'}
        with patch("openai_client.urllib.request.urlopen", side_effect=[http_response([reasoning, call]), http_response([final_message()])]) as http:
            initial = [{"role": "user", "content": "Return JSON. How many unfinished orders?"}]
            message, _ = complete(initial, TOOLS)
            self.assertEqual(message["tool_calls"][0]["id"], "call_fixture")
            complete(initial + [message, {"role": "tool", "tool_call_id": "call_fixture", "content": '{"count":34}'}], TOOLS)
        items = json.loads(http.call_args.args[0].data)["input"]
        self.assertEqual(items[1:3], [reasoning, call])
        self.assertEqual(items[3], {"type": "function_call_output", "call_id": "call_fixture", "output": '{"count":34}'})

    def test_agent_retries_invalid_numbers_with_responses_state(self):
        reasoning = {"type": "reasoning", "id": "rs_fixture", "summary": [], "encrypted_content": "encrypted-fixture"}
        call = {"type": "function_call", "id": "fc_fixture", "call_id": "call_fixture",
                "name": "query_orders", "arguments": '{"status":"IN_PROGRESS"}'}
        correction = {"type": "reasoning", "id": "rs_correction", "summary": [], "encrypted_content": "correction-fixture"}
        with tempfile.TemporaryDirectory() as folder, patch("openai_client.urllib.request.urlopen", side_effect=[
                http_response([reasoning, call]), http_response([correction, final_message("999 orders")]),
                http_response([final_message()])]) as http:
            store = Store(Path(folder) / "isolated.db")
            result = Copilot(Factory(), store).ask("How many unfinished orders?")
            self.assertEqual(result["summary"], "34 orders")
            self.assertEqual(result["model"], MODEL)
            self.assertEqual(result["evidence"]["E1"]["facts"]["count"], 34)
            self.assertEqual(store.activity()["actions"], [])
            self.assertIn(correction, json.loads(http.call_args.args[0].data)["input"])

    def test_disabled_network_precedes_key_and_http(self):
        with patch.dict(os.environ, {"OPENAI_NETWORK_ENABLED": "false"}), patch("openai_client.api_key") as key, \
                patch("openai_client.urllib.request.urlopen") as http:
            with self.assertRaises(ModelError):
                complete([{"role": "user", "content": "Private fixture"}])
            key.assert_not_called()
            http.assert_not_called()

    def test_deepseek_configuration_cannot_enable_openai_or_supply_its_key(self):
        legacy = {"DEEPSEEK_NETWORK_ENABLED": True, "DEEPSEEK_API_KEY": "old-provider-key"}
        with patch.dict(os.environ, {}, clear=True), patch("openai_client.local_settings", return_value=legacy):
            self.assertFalse(network_enabled())
            self.assertEqual(api_key(), "")

    def test_http_errors_never_expose_provider_body_or_credentials(self):
        for status in (400, 401, 403, 404, 429, 500):
            error = urllib.error.HTTPError(ENDPOINT, status, "fixture-key", {}, io.BytesIO(b"private response fixture-key"))
            with self.subTest(status=status), patch("openai_client.urllib.request.urlopen", side_effect=error):
                with self.assertRaises(ModelError) as raised:
                    complete([{"role": "user", "content": "Return JSON."}])
                self.assertNotIn("fixture-key", str(raised.exception))
                self.assertNotIn("private response", str(raised.exception))

    def test_incomplete_and_missing_answers_are_rejected(self):
        for response in (http_response([], status="incomplete"), http_response([])):
            with patch("openai_client.urllib.request.urlopen", return_value=response):
                with self.assertRaises(ModelError):
                    complete([{"role": "user", "content": "Return JSON."}])

    def test_quota_error_is_distinguished_from_rate_limiting(self):
        for code in ("insufficient_quota", "credit_balance_exhausted"):
            body = json.dumps({"error": {"code": code, "type": "insufficient_quota", "message": "private fixture-key"}}).encode()
            error = urllib.error.HTTPError(ENDPOINT, 429, "fixture", {}, io.BytesIO(body))
            with self.subTest(code=code), patch("openai_client.urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(ModelError, "Add API credits") as raised:
                    complete([{"role": "user", "content": "Return JSON."}])
                self.assertNotIn("fixture-key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
