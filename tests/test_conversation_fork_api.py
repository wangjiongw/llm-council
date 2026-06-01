import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ConversationForkApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")
        storage.update_conversation_title("conv-1", "Root chat")
        storage.update_context_policy("conv-1", {"recent_turns": 3, "use_pinned": False})
        user0 = storage.add_user_message("conv-1", "first instruction")
        assistant0 = storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "first answer"},
            metadata={"mode": "quick", "context_snapshot": {"mode": "quick"}},
        )
        storage.create_turn_record(
            "conv-1",
            user_message_index=user0,
            assistant_message_index=assistant0,
            mode="quick",
            context_snapshot={"mode": "quick"},
            status="complete",
        )
        user1 = storage.add_user_message("conv-1", "second instruction")
        assistant1 = storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "second answer"},
            metadata={"mode": "quick"},
        )
        storage.create_turn_record(
            "conv-1",
            user_message_index=user1,
            assistant_message_index=assistant1,
            mode="quick",
            context_snapshot={"mode": "quick"},
            status="complete",
        )
        storage.set_message_pinned("conv-1", 0, True)

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_fork_conversation_preserves_prefix_and_leaves_parent_intact(self):
        response = self.client.post(
            "/api/conversations/conv-1/fork",
            json={"message_index": 1},
        )

        self.assertEqual(response.status_code, 200)
        branch = response.json()
        self.assertNotEqual(branch["id"], "conv-1")
        self.assertEqual(branch["branch_parent_id"], "conv-1")
        self.assertEqual(branch["branch_from_message_index"], 1)
        self.assertEqual(branch["title"], "Root chat (branch)")
        self.assertEqual(len(branch["messages"]), 2)
        self.assertEqual(branch["messages"][0]["content"], "first instruction")
        self.assertTrue(branch["messages"][0]["pinned"])
        self.assertEqual(len(branch["turns"]), 1)
        self.assertEqual(branch["turns"][0]["user_message_index"], 0)
        self.assertEqual(branch["turns"][0]["assistant_message_index"], 1)
        self.assertEqual(branch["context_summary"]["content"], "")
        self.assertEqual(branch["context_policy"]["recent_turns"], 3)
        self.assertFalse(branch["context_policy"]["use_pinned"])

        parent = storage.get_conversation("conv-1")
        self.assertEqual(len(parent["messages"]), 4)
        self.assertEqual(len(parent["turns"]), 2)

    def test_fork_from_unanswered_user_message_drops_invalid_turn_id(self):
        response = self.client.post(
            "/api/conversations/conv-1/fork",
            json={"message_index": 2},
        )

        self.assertEqual(response.status_code, 200)
        branch = response.json()
        self.assertEqual(len(branch["messages"]), 3)
        self.assertEqual(len(branch["turns"]), 1)
        self.assertNotIn("turn_id", branch["messages"][2])

    def test_fork_rejects_invalid_message_index(self):
        response = self.client.post(
            "/api/conversations/conv-1/fork",
            json={"message_index": 99},
        )

        self.assertEqual(response.status_code, 400)

    def test_fork_unknown_conversation_returns_404(self):
        response = self.client.post(
            "/api/conversations/missing/fork",
            json={"message_index": 0},
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
