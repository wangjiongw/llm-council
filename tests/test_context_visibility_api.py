import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextVisibilityApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")
        storage.add_user_message("conv-1", "sensitive scratchpad")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_exclude_and_include_message_context_visibility(self):
        response = self.client.patch(
            "/api/conversations/conv-1/messages/0/context-visibility",
            json={"excluded": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["context_excluded"])
        message = payload["conversation"]["messages"][0]
        self.assertTrue(message["context_excluded"])
        self.assertIn("context_excluded_at", message)

        response = self.client.patch(
            "/api/conversations/conv-1/messages/0/context-visibility",
            json={"excluded": False},
        )

        self.assertEqual(response.status_code, 200)
        message = response.json()["conversation"]["messages"][0]
        self.assertFalse(message["context_excluded"])
        self.assertNotIn("context_excluded_at", message)

    def test_excluding_message_clears_cached_context_summary(self):
        conversation = storage.get_conversation("conv-1")
        conversation["context_summary"] = {
            "content": "summary that may mention sensitive scratchpad",
            "covered_messages": 1,
            "updated_at": "2026-01-01T00:00:00",
        }
        storage.save_conversation(conversation)

        response = self.client.patch(
            "/api/conversations/conv-1/messages/0/context-visibility",
            json={"excluded": True},
        )

        self.assertEqual(response.status_code, 200)
        summary = response.json()["conversation"]["context_summary"]
        self.assertEqual(summary["content"], "")
        self.assertEqual(summary["covered_messages"], 0)
        self.assertIsNone(summary["updated_at"])

    def test_context_visibility_rejects_invalid_message_index(self):
        response = self.client.patch(
            "/api/conversations/conv-1/messages/9/context-visibility",
            json={"excluded": True},
        )

        self.assertEqual(response.status_code, 400)

    def test_context_visibility_unknown_conversation_returns_404(self):
        response = self.client.patch(
            "/api/conversations/missing/messages/0/context-visibility",
            json={"excluded": True},
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
