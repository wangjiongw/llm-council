import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextAuditApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_context_audit_returns_turn_snapshot_and_runs(self):
        user_index = storage.add_user_message("conv-1", "hello")
        assistant_index = storage.add_assistant_message(
            "conv-1",
            [{"model": "m1", "status": "success", "response": "draft"}],
            [{"model": "m2", "status": "failed", "error_type": "timeout", "ranking": ""}],
            {"model": "chair", "status": "success", "response": "final", "id": "resp-1", "usage": {"total_tokens": 7}},
            metadata={"mode": "council", "context_snapshot": {"mode": "council", "included_history_messages": 2}},
        )
        turn = storage.create_turn_record(
            "conv-1",
            user_message_index=user_index,
            assistant_message_index=assistant_index,
            mode="council",
            context_snapshot={"mode": "council", "included_history_messages": 2},
            status="running",
        )
        storage.update_turn_from_assistant("conv-1", turn["id"], status="complete")

        response = self.client.get("/api/conversations/conv-1/context")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["conversation_id"], "conv-1")
        self.assertEqual(payload["turn_count"], 1)
        self.assertEqual(payload["turns"][0]["status"], "complete")
        self.assertEqual(payload["turns"][0]["context_snapshot"]["included_history_messages"], 2)
        self.assertEqual([run["stage"] for run in payload["turns"][0]["runs"]], ["stage1", "stage2", "stage3"])
        self.assertEqual(payload["turns"][0]["runs"][2]["response_id"], "resp-1")

    def test_context_audit_unknown_conversation_returns_404(self):
        response = self.client.get("/api/conversations/missing/context")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
