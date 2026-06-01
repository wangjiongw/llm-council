import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextSummaryApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")
        storage.update_context_policy("conv-1", {"recent_turns": 1})

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def _add_turn(self, user_text, assistant_text):
        storage.add_user_message("conv-1", user_text)
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": assistant_text},
            metadata={"mode": "quick"},
        )

    def test_rebuild_summary_uses_policy_older_active_messages(self):
        for index in range(4):
            self._add_turn(f"user {index}", f"assistant {index}")
        storage.set_message_context_excluded("conv-1", 0, True)

        with patch(
            "backend.storage.summarize_conversation_segment",
            new=AsyncMock(return_value="manual rebuilt summary"),
        ) as summarize_mock:
            response = self.client.post("/api/conversations/conv-1/context-summary/rebuild")

        self.assertEqual(response.status_code, 200)
        summary = response.json()["context_summary"]
        self.assertEqual(summary["content"], "manual rebuilt summary")
        self.assertEqual(summary["covered_messages"], 5)

        summarized_text = "\n".join(
            message["content"]
            for call in summarize_mock.await_args_list
            for message in call.args[0]
        )
        self.assertNotIn("user 0", summarized_text)
        self.assertIn("assistant 0", summarized_text)
        self.assertNotIn("user 3", summarized_text)

    def test_rebuild_summary_clears_when_no_older_history(self):
        self._add_turn("only recent", "answer")
        response = self.client.post("/api/conversations/conv-1/context-summary/rebuild")

        self.assertEqual(response.status_code, 200)
        summary = response.json()["context_summary"]
        self.assertEqual(summary["content"], "")
        self.assertEqual(summary["covered_messages"], 0)
        self.assertIsNone(summary["updated_at"])

    def test_clear_summary_resets_cached_state(self):
        conversation = storage.get_conversation("conv-1")
        conversation["context_summary"] = {
            "content": "stale summary",
            "covered_messages": 7,
            "updated_at": "2026-01-01T00:00:00",
        }
        storage.save_conversation(conversation)

        response = self.client.delete("/api/conversations/conv-1/context-summary")

        self.assertEqual(response.status_code, 200)
        summary = response.json()["context_summary"]
        self.assertEqual(summary["content"], "")
        self.assertEqual(summary["covered_messages"], 0)
        self.assertIsNone(summary["updated_at"])

    def test_summary_actions_unknown_conversation_return_404(self):
        rebuild = self.client.post("/api/conversations/missing/context-summary/rebuild")
        clear = self.client.delete("/api/conversations/missing/context-summary")

        self.assertEqual(rebuild.status_code, 404)
        self.assertEqual(clear.status_code, 404)


if __name__ == "__main__":
    unittest.main()
