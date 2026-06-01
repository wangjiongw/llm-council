import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from backend import storage


class ContextPackageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "CONVERSATION_CONTEXT_TOKEN_BUDGET",
                "CONVERSATION_CONTEXT_MESSAGE_CHAR_LIMIT",
                "CONVERSATION_CONTEXT_RECENT_TURNS",
                "CONVERSATION_CONTEXT_PIN_MESSAGE_CHAR_LIMIT",
                "CONVERSATION_CONTEXT_PIN_MAX_CHARS",
                "CONVERSATION_CONTEXT_MEMORY_ITEM_CHAR_LIMIT",
                "CONVERSATION_CONTEXT_MEMORY_MAX_CHARS",
            )
        }

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _add_turn(self, conversation_id, user_text, assistant_text):
        storage.add_user_message(conversation_id, user_text)
        storage.add_assistant_message(
            conversation_id,
            [],
            [],
            {"model": "m", "status": "success", "response": assistant_text},
            metadata={"mode": "quick"},
        )

    async def test_context_package_uses_summary_recent_messages_and_snapshot(self):
        os.environ["CONVERSATION_CONTEXT_RECENT_TURNS"] = "2"
        storage.create_conversation("conv-1")
        for index in range(12):
            self._add_turn("conv-1", f"old user {index}", f"old assistant {index}")

        current_content = [
            {"type": "text", "text": "question"},
            {"type": "text", "text": "\n\n[Attached file: notes.md]\nimportant\n[/Attached file: notes.md]"},
        ]

        with patch(
            "backend.storage.summarize_conversation_segment",
            new=AsyncMock(return_value="summary of older goals and decisions"),
        ):
            package = await storage.build_context_package(
                "conv-1",
                current_content=current_content,
                mode="council",
            )

        messages = package["messages"]
        snapshot = package["snapshot"]

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("summary of older goals", messages[0]["content"])
        self.assertTrue(all(set(message.keys()) <= {"role", "content"} for message in messages))
        self.assertEqual(len(package["source_messages"]), len(messages))
        self.assertEqual(package["source_messages"][0]["source"], "summary")
        self.assertTrue(any(
            isinstance(message.get("message_index"), int)
            for message in package["source_messages"]
            if message.get("source") == "history"
        ))
        self.assertEqual(snapshot["strategy"], "summary_recent_pinned_policy_v1")
        self.assertEqual(snapshot["context_policy"]["recent_turns"], 2)
        self.assertEqual(snapshot["mode"], "council")
        self.assertTrue(snapshot["summary_used"])
        self.assertEqual(snapshot["raw_history_messages"], 24)
        self.assertEqual(snapshot["included_history_messages"], 4)
        self.assertEqual(snapshot["current_turn"]["text_attachment_count"], 1)
        self.assertEqual(snapshot["current_turn"]["file_names"], ["notes.md"])
        breakdown = snapshot["budget_breakdown"]
        self.assertGreater(breakdown["summary_tokens"], 0)
        self.assertGreater(breakdown["recent_history_tokens"], 0)
        self.assertGreater(breakdown["current_turn_tokens"], 0)
        self.assertEqual(breakdown["history_context_tokens"], snapshot["estimated_context_tokens"])
        self.assertEqual(
            breakdown["estimated_request_tokens"],
            breakdown["history_context_tokens"] + breakdown["current_turn_tokens"],
        )

    async def test_history_image_payload_is_not_replayed_as_context(self):
        storage.create_conversation("conv-1")
        storage.add_user_message(
            "conv-1",
            [
                {"type": "text", "text": "please inspect this image"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,SECRET_PAYLOAD"}},
            ],
        )
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "image answer"},
            metadata={"mode": "quick"},
        )

        package = await storage.build_context_package(
            "conv-1",
            current_content="follow up",
            mode="quick",
        )

        joined_context = "\n".join(str(message.get("content", "")) for message in package["messages"])
        self.assertNotIn("SECRET_PAYLOAD", joined_context)
        self.assertIn("earlier image attachment", joined_context)
        self.assertFalse(package["snapshot"]["current_turn"]["image_attachment_count"])

    async def test_pinned_old_message_is_included_outside_recent_window(self):
        os.environ["CONVERSATION_CONTEXT_RECENT_TURNS"] = "1"
        os.environ["CONVERSATION_CONTEXT_PIN_MESSAGE_CHAR_LIMIT"] = "1000"
        os.environ["CONVERSATION_CONTEXT_PIN_MAX_CHARS"] = "2000"
        storage.create_conversation("conv-1")
        self._add_turn("conv-1", "critical contract: always answer in tables", "ack")
        for index in range(1, 5):
            self._add_turn("conv-1", f"ordinary user {index}", f"ordinary assistant {index}")

        storage.set_message_pinned("conv-1", 0, True)

        package = await storage.build_context_package(
            "conv-1",
            current_content="next",
            mode="quick",
            summarize_older=False,
        )

        joined_context = "\n".join(str(message.get("content", "")) for message in package["messages"])
        snapshot = package["snapshot"]
        self.assertIn("Pinned user message #0", joined_context)
        self.assertIn("critical contract: always answer in tables", joined_context)
        self.assertIn("ordinary user 4", joined_context)
        self.assertEqual(snapshot["pinned_message_count"], 1)
        self.assertEqual(snapshot["included_pinned_messages"], 1)
        self.assertTrue(snapshot["pinned_context_used"])
        pinned_sources = [message for message in package["source_messages"] if message.get("source") == "pinned"]
        self.assertEqual(pinned_sources[0]["source_message_indexes"], [0])
        self.assertTrue(all("source_message_indexes" not in message for message in package["messages"]))
        self.assertGreater(snapshot["budget_breakdown"]["pinned_tokens"], 0)

    async def test_excluded_message_is_not_used_as_recent_summary_or_pinned_context(self):
        os.environ["CONVERSATION_CONTEXT_RECENT_TURNS"] = "1"
        os.environ["CONVERSATION_CONTEXT_PIN_MESSAGE_CHAR_LIMIT"] = "1000"
        os.environ["CONVERSATION_CONTEXT_PIN_MAX_CHARS"] = "2000"
        storage.create_conversation("conv-1")
        self._add_turn("conv-1", "secret old instruction", "secret old answer")
        for index in range(1, 5):
            self._add_turn("conv-1", f"ordinary user {index}", f"ordinary assistant {index}")

        storage.set_message_pinned("conv-1", 0, True)
        storage.set_message_context_excluded("conv-1", 0, True)
        storage.set_message_context_excluded("conv-1", 8, True)

        with patch(
            "backend.storage.summarize_conversation_segment",
            new=AsyncMock(return_value="summary without excluded content"),
        ) as summarize_mock:
            package = await storage.build_context_package(
                "conv-1",
                current_content="next",
                mode="quick",
            )

        joined_context = "\n".join(str(message.get("content", "")) for message in package["messages"])
        snapshot = package["snapshot"]
        summarized_text = "\n".join(
            str(message.get("content", ""))
            for call in summarize_mock.await_args_list
            for message in call.args[0]
        )

        self.assertNotIn("secret old instruction", joined_context)
        self.assertNotIn("ordinary user 4", joined_context)
        self.assertNotIn("secret old instruction", summarized_text)
        self.assertNotIn("ordinary user 4", summarized_text)
        self.assertEqual(snapshot["raw_history_messages"], 10)
        self.assertEqual(snapshot["excluded_history_messages"], 2)
        self.assertEqual(snapshot["pinned_message_count"], 0)
        self.assertFalse(snapshot["pinned_context_used"])

    async def test_context_policy_controls_recent_summary_and_pinned_context(self):
        storage.create_conversation("conv-1")
        self._add_turn("conv-1", "pinned should not appear", "ack")
        for index in range(1, 6):
            self._add_turn("conv-1", f"policy user {index}", f"policy assistant {index}")
        storage.set_message_pinned("conv-1", 0, True)
        storage.update_context_policy("conv-1", {
            "recent_turns": 1,
            "summarize_older": False,
            "use_pinned": False,
            "token_budget": 6000,
        })

        package = await storage.build_context_package(
            "conv-1",
            current_content="next",
            mode="quick",
        )

        joined_context = "\n".join(str(message.get("content", "")) for message in package["messages"])
        snapshot = package["snapshot"]
        self.assertNotIn("pinned should not appear", joined_context)
        self.assertIn("policy user 5", joined_context)
        self.assertNotIn("policy user 3", joined_context)
        self.assertFalse(snapshot["summary_used"])
        self.assertFalse(snapshot["pinned_context_used"])
        self.assertEqual(snapshot["context_policy"]["recent_turns"], 1)
        self.assertFalse(snapshot["context_policy"]["use_pinned"])

    async def test_context_memory_is_included_as_durable_system_context(self):
        storage.create_conversation("conv-1")
        storage.add_context_memory("conv-1", "Always compare API statelessness with server-managed context.")

        package = await storage.build_context_package(
            "conv-1",
            current_content="first question",
            mode="quick",
        )

        joined_context = "\n".join(str(message.get("content", "")) for message in package["messages"])
        snapshot = package["snapshot"]
        self.assertIn("Conversation memory", joined_context)
        self.assertIn("server-managed context", joined_context)
        self.assertEqual(package["messages"][0]["role"], "system")
        self.assertTrue(all(set(message.keys()) <= {"role", "content"} for message in package["messages"]))
        self.assertEqual(package["source_messages"][0]["source"], "memory")
        self.assertTrue(snapshot["memory_context_used"])
        self.assertEqual(snapshot["memory_count"], 1)
        self.assertEqual(snapshot["included_memory_items"], 1)
        self.assertGreater(snapshot["budget_breakdown"]["memory_tokens"], 0)

    async def test_context_memory_policy_can_disable_memory_context(self):
        storage.create_conversation("conv-1")
        storage.add_context_memory("conv-1", "Do not include this when memory is disabled.")
        storage.update_context_policy("conv-1", {"use_memory": False})

        package = await storage.build_context_package(
            "conv-1",
            current_content="first question",
            mode="quick",
        )

        joined_context = "\n".join(str(message.get("content", "")) for message in package["messages"])
        self.assertNotIn("Do not include this", joined_context)
        self.assertFalse(package["snapshot"]["memory_context_used"])
        self.assertEqual(package["snapshot"]["budget_breakdown"]["memory_tokens"], 0)

    async def test_context_package_respects_budget_by_dropping_oldest_recent_messages(self):
        os.environ["CONVERSATION_CONTEXT_TOKEN_BUDGET"] = "40"
        os.environ["CONVERSATION_CONTEXT_RECENT_TURNS"] = "10"
        storage.create_conversation("conv-1")
        for index in range(6):
            self._add_turn(
                "conv-1",
                f"user {index} " + ("u" * 1200),
                f"assistant {index} " + ("a" * 1200),
            )

        package = await storage.build_context_package(
            "conv-1",
            current_content="next",
            mode="quick",
            summarize_older=False,
        )

        snapshot = package["snapshot"]
        self.assertTrue(snapshot["truncated"])
        self.assertLess(snapshot["included_history_messages"], snapshot["raw_history_messages"])
        self.assertLessEqual(snapshot["estimated_context_tokens"], snapshot["budget_tokens"] + 80)


if __name__ == "__main__":
    unittest.main()
