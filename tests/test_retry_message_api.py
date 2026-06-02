import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class RetryMessageApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_retry_replaces_assistant_without_duplicating_user_message(self):
        user_index = storage.add_user_message("conv-1", "explain retry safety")
        assistant_index = storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "quick-old", "status": "success", "response": "old answer"},
            metadata={"mode": "quick", "context_snapshot": {"mode": "quick"}},
        )
        turn = storage.create_turn_record(
            "conv-1",
            user_message_index=user_index,
            assistant_message_index=assistant_index,
            mode="quick",
            context_snapshot={"mode": "quick"},
            status="complete",
        )
        storage.update_turn_from_assistant("conv-1", turn["id"], status="complete")

        quick_mock = AsyncMock(return_value={
            "model": "quick-new",
            "status": "success",
            "response": "new answer",
            "metadata": {"attempts": [{"model": "quick-new", "ok": True}]},
        })

        with patch("backend.main.quick_query", new=quick_mock):
            response = self.client.post(
                "/api/conversations/conv-1/messages/0/retry",
                json={"mode": "quick"},
            )

        self.assertEqual(response.status_code, 200)
        conversation = storage.get_conversation("conv-1")
        self.assertEqual([message["role"] for message in conversation["messages"]], ["user", "assistant"])
        self.assertEqual(conversation["messages"][0]["content"], "explain retry safety")
        self.assertEqual(conversation["messages"][1]["stage3"]["response"], "new answer")
        self.assertNotIn("old answer", str(conversation))
        self.assertEqual(len(conversation["turns"]), 1)
        self.assertEqual(conversation["turns"][0]["user_message_index"], 0)
        self.assertEqual(conversation["turns"][0]["assistant_message_index"], 1)
        self.assertEqual(conversation["turns"][0]["runs"][0]["model"], "quick-new")
        quick_mock.assert_awaited_once()
        self.assertIsNone(quick_mock.call_args.args[1])

    def test_retry_with_edit_updates_user_message_before_regeneration(self):
        storage.add_user_message("conv-1", "old prompt")
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "quick-old", "status": "success", "response": "old answer"},
            metadata={"mode": "quick"},
        )

        captured = {}

        async def fake_quick(content, conversation_history=None, event_callback=None, **_kwargs):
            captured["content"] = content
            return {
                "model": "quick-new",
                "status": "success",
                "response": "edited answer",
                "metadata": {"attempts": [{"model": "quick-new", "ok": True}]},
            }

        with patch("backend.main.quick_query", new=fake_quick):
            response = self.client.post(
                "/api/conversations/conv-1/messages/0/retry",
                json={"mode": "quick", "edited_content": "new edited prompt"},
            )

        self.assertEqual(response.status_code, 200)
        conversation = storage.get_conversation("conv-1")
        self.assertEqual([message["role"] for message in conversation["messages"]], ["user", "assistant"])
        self.assertEqual(conversation["messages"][0]["content"], "new edited prompt")
        self.assertEqual(conversation["messages"][1]["stage3"]["response"], "edited answer")
        self.assertEqual(captured["content"], "new edited prompt")
        self.assertNotIn("old prompt", str(conversation))
        self.assertNotIn("old answer", str(conversation))

    def test_retry_uses_prior_context_before_user_message(self):
        storage.add_user_message("conv-1", "first")
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "first answer"},
            metadata={"mode": "quick"},
        )
        storage.add_user_message("conv-1", "second")
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "quick-old", "status": "success", "response": "old second answer"},
            metadata={"mode": "quick"},
        )

        captured_history = {}

        async def fake_quick(content, conversation_history=None, event_callback=None, **_kwargs):
            captured_history["content"] = content
            captured_history["history"] = conversation_history
            return {
                "model": "quick-new",
                "status": "success",
                "response": "new second answer",
                "metadata": {"attempts": [{"model": "quick-new", "ok": True}]},
            }

        with patch("backend.main.quick_query", new=fake_quick):
            response = self.client.post(
                "/api/conversations/conv-1/messages/2/retry",
                json={"mode": "quick"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured_history["content"], "second")
        joined_history = "\n".join(message["content"] for message in captured_history["history"])
        self.assertIn("first", joined_history)
        self.assertIn("first answer", joined_history)
        self.assertNotIn("second", joined_history)
        self.assertNotIn("old second answer", joined_history)

    def test_truncate_removes_suffix_turns_and_invalidates_summary(self):
        for index in range(2):
            user_index = storage.add_user_message("conv-1", f"user {index}")
            assistant_index = storage.add_assistant_message(
                "conv-1",
                [],
                [],
                {"model": "m", "status": "success", "response": f"answer {index}"},
                metadata={"mode": "quick"},
            )
            turn = storage.create_turn_record(
                "conv-1",
                user_message_index=user_index,
                assistant_message_index=assistant_index,
                mode="quick",
                context_snapshot={"mode": "quick"},
                status="complete",
            )
            storage.update_turn_from_assistant("conv-1", turn["id"], status="complete")

        conversation = storage.get_conversation("conv-1")
        conversation["context_summary"] = {"content": "stale", "covered_messages": 4, "updated_at": "now"}
        storage.save_conversation(conversation)

        response = self.client.delete("/api/conversations/conv-1/messages/from/2")

        self.assertEqual(response.status_code, 200)
        conversation = response.json()
        self.assertEqual(len(conversation["messages"]), 2)
        self.assertEqual(len(conversation["turns"]), 1)
        self.assertEqual(conversation["context_summary"]["content"], "")
        self.assertEqual(conversation["context_summary"]["covered_messages"], 0)


if __name__ == "__main__":
    unittest.main()
