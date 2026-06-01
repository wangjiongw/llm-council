import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextPreviewApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")
        storage.add_user_message("conv-1", "visible instruction")
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "visible answer"},
            metadata={"mode": "quick"},
        )
        storage.add_user_message("conv-1", "hidden scratchpad")
        storage.set_message_context_excluded("conv-1", 2, True)

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_preview_returns_next_context_without_saving_turn(self):
        response = self.client.post(
            "/api/conversations/conv-1/context/preview",
            json={"content": "next question", "mode": "quick"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        joined_context = "\n".join(message.get("content", "") for message in payload["messages"])
        self.assertEqual(payload["mode"], "quick")
        self.assertEqual([message.get("message_index") for message in payload["messages"]], [0, 1])
        self.assertEqual([message.get("source") for message in payload["messages"]], ["history", "history"])
        self.assertIn("visible instruction", joined_context)
        self.assertNotIn("hidden scratchpad", joined_context)
        self.assertEqual(payload["snapshot"]["raw_history_messages"], 3)
        self.assertEqual(payload["snapshot"]["excluded_history_messages"], 1)
        self.assertEqual(len(storage.get_conversation("conv-1")["messages"]), 3)

    def test_preview_rejects_invalid_mode(self):
        response = self.client.post(
            "/api/conversations/conv-1/context/preview",
            json={"content": "next question", "mode": "slow"},
        )

        self.assertEqual(response.status_code, 400)

    def test_preview_unknown_conversation_returns_404(self):
        response = self.client.post(
            "/api/conversations/missing/context/preview",
            json={"content": "next question", "mode": "quick"},
        )

        self.assertEqual(response.status_code, 404)

    def test_file_preview_processes_attachments_without_saving_turn(self):
        response = self.client.post(
            "/api/conversations/conv-1/context/preview/files",
            data={"content": "look for budget", "mode": "council"},
            files=[("files", ("notes.txt", b"budget notes\nkeep this in scope", "text/plain"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "council")
        self.assertEqual(payload["file_metadata"][0]["name"], "notes.txt")
        self.assertEqual(payload["snapshot"]["current_turn"]["text_attachment_count"], 1)
        self.assertEqual(payload["snapshot"]["current_turn"]["file_names"], ["notes.txt"])
        self.assertEqual(len(storage.get_conversation("conv-1")["messages"]), 3)


if __name__ == "__main__":
    unittest.main()
