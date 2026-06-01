import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend import storage


class StorageConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_concurrent_user_message_appends_do_not_overwrite_each_other(self):
        message_count = 40

        def add_message(index):
            return storage.add_user_message("conv-1", f"message-{index}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            indexes = list(executor.map(add_message, range(message_count)))

        conversation = storage.get_conversation("conv-1")
        contents = [message["content"] for message in conversation["messages"]]

        self.assertEqual(len(conversation["messages"]), message_count)
        self.assertEqual(set(contents), {f"message-{index}" for index in range(message_count)})
        self.assertEqual(len(set(indexes)), message_count)

    def test_atomic_save_does_not_leave_temp_files_after_successful_write(self):
        storage.add_user_message("conv-1", "hello")
        storage.update_conversation_title("conv-1", "Concurrent safe")

        leftover_temp_files = [
            path.name for path in __import__("pathlib").Path(self.tmpdir.name).iterdir()
            if ".tmp-" in path.name
        ]

        self.assertEqual(leftover_temp_files, [])
        self.assertEqual(storage.get_conversation("conv-1")["title"], "Concurrent safe")


if __name__ == "__main__":
    unittest.main()
