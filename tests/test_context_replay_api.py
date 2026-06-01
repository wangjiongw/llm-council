import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextReplayApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def _seed_two_turns(self):
        storage.add_context_memory("conv-1", "Durable memory: API calls are stateless.")
        first_user_index = storage.add_user_message("conv-1", "first question")
        first_assistant_index = storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "first answer"},
            metadata={"mode": "quick"},
        )
        storage.create_turn_record(
            "conv-1",
            user_message_index=first_user_index,
            assistant_message_index=first_assistant_index,
            mode="quick",
            context_snapshot={"mode": "quick", "estimated_context_tokens": 5},
            status="complete",
        )

        second_user_index = storage.add_user_message("conv-1", "second question")
        second_assistant_index = storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "second answer"},
            metadata={"mode": "quick", "context_snapshot": {"mode": "quick", "estimated_context_tokens": 9}},
        )
        second_turn = storage.create_turn_record(
            "conv-1",
            user_message_index=second_user_index,
            assistant_message_index=second_assistant_index,
            mode="quick",
            context_snapshot={"mode": "quick", "estimated_context_tokens": 9},
            status="complete",
        )
        return second_user_index, second_turn

    def test_replay_rebuilds_context_for_stored_user_turn_without_mutating_history(self):
        message_index, turn = self._seed_two_turns()
        original_message_count = len(storage.get_conversation("conv-1")["messages"])

        response = self.client.post(
            f"/api/conversations/conv-1/messages/{message_index}/context/replay",
            json={},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        joined_context = "\n".join(message.get("content", "") for message in payload["messages"])
        self.assertEqual(payload["mode"], "quick")
        self.assertEqual(payload["replay_kind"], "current_policy_rebuild")
        self.assertFalse(payload["comparison"]["available"])
        self.assertEqual(payload["message_index"], message_index)
        self.assertEqual(payload["turn_id"], turn["id"])
        self.assertEqual(payload["assistant_message_index"], 3)
        self.assertEqual(payload["saved_snapshot"]["estimated_context_tokens"], 9)
        self.assertIn("Durable memory", joined_context)
        self.assertIn("first question", joined_context)
        self.assertIn("first answer", joined_context)
        self.assertNotIn("second question", joined_context)
        self.assertNotIn("second answer", joined_context)
        self.assertEqual(len(storage.get_conversation("conv-1")["messages"]), original_message_count)
        self.assertEqual([message.get("source") for message in payload["messages"]], ["memory", "history", "history"])

    def test_replay_prefers_saved_context_payload_when_available(self):
        message_index, turn = self._seed_two_turns()
        storage.update_turn_record(
            "conv-1",
            turn["id"],
            context_payload={
                "schema": "context_payload_v1",
                "model_messages": [{"role": "system", "content": "saved model context"}],
                "audit_messages": [{"role": "system", "content": "saved audit context", "source": "memory"}],
                "current_message": {"role": "user", "content": "second question"},
            },
        )

        response = self.client.post(
            f"/api/conversations/conv-1/messages/{message_index}/context/replay",
            json={},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["replay_kind"], "saved_context_payload")
        self.assertEqual(payload["messages"][0]["content"], "saved audit context")
        self.assertEqual(payload["saved_context_payload"]["current_message"], {"role": "user", "content": "second question"})
        rebuilt_context = "\n".join(message.get("content", "") for message in payload["rebuilt_messages"])
        self.assertIn("first question", rebuilt_context)
        self.assertEqual(payload["rebuilt_message_count"], len(payload["rebuilt_messages"]))
        comparison = payload["comparison"]
        self.assertTrue(comparison["available"])
        self.assertFalse(comparison["same_order"])
        self.assertFalse(comparison["same_message_set"])
        self.assertEqual(comparison["saved_only_count"], 1)
        self.assertEqual(comparison["rebuilt_only_count"], 3)
        self.assertEqual(comparison["saved_only_preview"][0]["content_preview"], "saved audit context")
        self.assertGreater(comparison["rebuilt_estimated_tokens"], 0)

    def test_replay_can_override_mode(self):
        message_index, _turn = self._seed_two_turns()

        response = self.client.post(
            f"/api/conversations/conv-1/messages/{message_index}/context/replay",
            json={"mode": "council"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "council")

    def test_replay_rejects_invalid_targets(self):
        self._seed_two_turns()

        non_user = self.client.post(
            "/api/conversations/conv-1/messages/1/context/replay",
            json={},
        )
        missing = self.client.post(
            "/api/conversations/missing/messages/0/context/replay",
            json={},
        )
        bad_mode = self.client.post(
            "/api/conversations/conv-1/messages/2/context/replay",
            json={"mode": "slow"},
        )

        self.assertEqual(non_user.status_code, 400)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(bad_mode.status_code, 400)


if __name__ == "__main__":
    unittest.main()
