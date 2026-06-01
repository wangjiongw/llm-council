import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextMemoryApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_add_update_disable_and_delete_context_memory(self):
        create = self.client.post(
            "/api/conversations/conv-1/context-memory",
            json={"content": "Project uses a stateless model API."},
        )

        self.assertEqual(create.status_code, 200)
        memory = create.json()["memory"]
        self.assertTrue(memory["enabled"])
        self.assertEqual(memory["content"], "Project uses a stateless model API.")

        update = self.client.patch(
            f"/api/conversations/conv-1/context-memory/{memory['id']}",
            json={"content": "Server owns context assembly.", "enabled": False},
        )

        self.assertEqual(update.status_code, 200)
        updated = update.json()["memory"]
        self.assertEqual(updated["content"], "Server owns context assembly.")
        self.assertFalse(updated["enabled"])

        listed = self.client.get("/api/conversations/conv-1/context-memory")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["context_memory"]), 1)

        delete = self.client.delete(f"/api/conversations/conv-1/context-memory/{memory['id']}")
        self.assertEqual(delete.status_code, 200)
        self.assertEqual(delete.json()["context_memory"], [])

    def test_context_memory_validation_and_unknown_conversation(self):
        empty = self.client.post(
            "/api/conversations/conv-1/context-memory",
            json={"content": "   "},
        )
        missing = self.client.get("/api/conversations/missing/context-memory")

        self.assertEqual(empty.status_code, 400)
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
