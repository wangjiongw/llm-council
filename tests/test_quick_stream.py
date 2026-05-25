import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


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
        async def fake_query_model(model, messages, timeout=None, event_callback=None):
            if event_callback:
                await event_callback({
                    "status": "first_event",
                    "first_event_seconds": 0.01,
                })
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


if __name__ == "__main__":
    unittest.main()
