import tempfile
import unittest

from backend import storage


class AssistantPartialStorageTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_partial_assistant_updates_same_message(self):
        storage.create_conversation("conv-1")
        storage.add_user_message("conv-1", "hello")

        index = storage.create_assistant_partial("conv-1")
        storage.update_assistant_partial(
            "conv-1",
            index,
            {
                "stage1": [{"model": "a", "status": "success", "response": "answer"}],
                "loading": {"stage1": False, "stage2": True},
                "modelStatus": {
                    "stage1": {
                        "a": {"model": "a", "status": "success"},
                    }
                },
            },
        )
        storage.update_assistant_partial(
            "conv-1",
            index,
            {
                "stage2": [{"model": "b", "status": "success", "ranking": "rank"}],
                "metadata": {"label_to_model": {"Response A": "a"}},
                "loading": {"stage2": False, "stage3": True},
            },
        )

        conversation = storage.get_conversation("conv-1")
        self.assertEqual(len(conversation["messages"]), 2)
        assistant = conversation["messages"][index]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["status"], "running")
        self.assertEqual(assistant["stage1"][0]["response"], "answer")
        self.assertEqual(assistant["stage2"][0]["ranking"], "rank")
        self.assertFalse(assistant["loading"]["stage1"])
        self.assertFalse(assistant["loading"]["stage2"])
        self.assertTrue(assistant["loading"]["stage3"])
        self.assertEqual(assistant["modelStatus"]["stage1"]["a"]["status"], "success")
        self.assertEqual(assistant["metadata"]["label_to_model"]["Response A"], "a")

    def test_history_skips_incomplete_assistant_partial(self):
        storage.create_conversation("conv-1")
        storage.add_user_message("conv-1", "hello")
        storage.create_assistant_partial("conv-1")

        history = storage.get_conversation_history("conv-1")

        self.assertEqual(history, [{"role": "user", "content": "hello"}])

    def test_history_skips_context_excluded_messages(self):
        storage.create_conversation("conv-1")
        storage.add_user_message("conv-1", "visible question")
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "hidden answer"},
        )
        storage.add_user_message("conv-1", "hidden question")
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "visible answer"},
        )
        storage.set_message_context_excluded("conv-1", 1, True)
        storage.set_message_context_excluded("conv-1", 2, True)

        history = storage.get_conversation_history("conv-1")

        self.assertEqual(history, [
            {"role": "user", "content": "visible question"},
            {"role": "assistant", "content": "visible answer"},
        ])


if __name__ == "__main__":
    unittest.main()
