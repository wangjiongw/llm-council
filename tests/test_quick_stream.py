import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app
from backend.provider_audit import canonical_digest, make_provider_request_audit


class QuickStreamTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_quick_stream_persists_running_turn_as_complete(self):
        async def fake_query_model(
            model,
            messages,
            timeout=None,
            event_callback=None,
            provider_audit_callback=None,
            audit_context=None,
            call_kind="model",
            stage="model",
            provider_function="query_model",
            attempt=None,
        ):
            if event_callback:
                await event_callback({
                    "status": "first_event",
                    "first_event_seconds": 0.01,
                })
            if provider_audit_callback:
                provider_audit_callback(make_provider_request_audit(
                    model=model,
                    messages=messages,
                    stream=True,
                    call_kind=call_kind,
                    stage=stage,
                    provider_function=provider_function,
                    source_map=(audit_context or {}).get("source_map"),
                    turn_lineage=(audit_context or {}).get("turn_lineage"),
                    attempt=attempt,
                    metadata=(audit_context or {}).get("metadata"),
                ))
            return {
                "status": "success",
                "model": model,
                "content": "quick ok",
                "id": "resp-1",
                "usage": {},
                "finish_reason": "stop",
                "duration_seconds": 0.02,
                "first_event_seconds": 0.01,
                "streamed": True,
            }

        with (
            patch("backend.main.generate_conversation_title", new=AsyncMock(return_value="Quick title")),
            patch("backend.council.model_name", return_value="quick-model"),
            patch("backend.council.model_list", return_value=[]),
            patch("backend.council.query_model", new=AsyncMock(side_effect=fake_query_model)),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/quick/stream",
                json={"content": "hello quick"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "quick_start"', response.text)
        self.assertIn('"type": "quick_model_start"', response.text)
        self.assertIn('"type": "quick_model_first_event"', response.text)
        self.assertIn('"type": "quick_complete"', response.text)

        conversation = storage.get_conversation("conv-1")
        self.assertEqual(conversation["title"], "Quick title")
        self.assertEqual(len(conversation["messages"]), 2)
        self.assertEqual(conversation["messages"][0]["role"], "user")
        self.assertEqual(conversation["messages"][0]["content"], "hello quick")

        assistant = conversation["messages"][1]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["status"], "complete")
        self.assertEqual(assistant["stage1"], [])
        self.assertEqual(assistant["stage2"], [])
        self.assertEqual(assistant["stage3"]["status"], "success")
        self.assertEqual(assistant["stage3"]["response"], "quick ok")
        self.assertEqual(assistant["metadata"]["mode"], "quick")
        self.assertEqual(assistant["metadata"]["attempts"], [{"model": "quick-model", "ok": True}])
        self.assertFalse(assistant["loading"]["stage3"])
        self.assertEqual(
            assistant["modelStatus"]["stage3"]["quick-model"]["status"],
            "success",
        )

        turns = conversation["turns"]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["mode"], "quick")
        self.assertEqual(turns[0]["status"], "complete")
        self.assertEqual(turns[0]["user_message_index"], 0)
        self.assertEqual(turns[0]["assistant_message_index"], 1)
        self.assertEqual(turns[0]["context_snapshot"]["mode"], "quick")
        self.assertEqual(turns[0]["context_payload"]["schema"], "context_payload_v2")
        self.assertIn("context_package_audit", turns[0]["context_payload"])
        self.assertEqual(turns[0]["context_payload"]["model_messages"], [])
        self.assertEqual(turns[0]["context_payload"]["audit_messages"], [])
        provider_audit = turns[0]["context_payload"]["provider_request_audit"]
        self.assertEqual(len(provider_audit), 1)
        self.assertEqual(provider_audit[0]["call_kind"], "quick")
        self.assertEqual(provider_audit[0]["stage"], "quick")
        self.assertEqual(provider_audit[0]["turn_lineage"]["user_message_index"], 0)
        self.assertEqual(provider_audit[0]["turn_lineage"]["turn_id"], turns[0]["id"])
        self.assertEqual(provider_audit[0]["source_map"]["current_message_ref"]["message_index"], 0)
        self.assertEqual(canonical_digest(provider_audit[0]["payload_preview"]), provider_audit[0]["digest"])
        self.assertEqual(turns[0]["context_payload"]["current_message"], {"role": "user", "content": "hello quick"})
        self.assertEqual(turns[0]["runs"][0]["stage"], "stage3")
        self.assertEqual(turns[0]["runs"][0]["model"], "quick-model")

        audit = self.client.get("/api/conversations/conv-1/context")
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.json()["turn_count"], 1)
        self.assertEqual(audit.json()["turns"][0]["id"], turns[0]["id"])

    def test_quick_stream_persists_failed_placeholder_on_error(self):
        with (
            patch("backend.main.generate_conversation_title", new=AsyncMock(return_value="Quick title")),
            patch("backend.main.quick_query", new=AsyncMock(side_effect=RuntimeError("provider down"))),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/quick/stream",
                json={"content": "hello quick"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "error"', response.text)

        conversation = storage.get_conversation("conv-1")
        self.assertEqual(len(conversation["messages"]), 2)
        assistant = conversation["messages"][1]
        self.assertEqual(assistant["status"], "failed")
        self.assertEqual(assistant["metadata"]["mode"], "quick")
        self.assertEqual(assistant["stage3"]["status"], "failed")
        self.assertIn("provider down", assistant["error"])
        self.assertFalse(assistant["loading"]["stage3"])
        self.assertEqual(conversation["turns"][0]["status"], "failed")
        self.assertEqual(conversation["turns"][0]["context_snapshot"]["mode"], "quick")
        self.assertEqual(conversation["turns"][0]["runs"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
