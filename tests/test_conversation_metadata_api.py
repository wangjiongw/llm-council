import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend import storage


class ConversationMetadataAPITest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")
        storage.create_conversation("conv-2")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_patch_updates_conversation_metadata(self):
        response = self.client.patch(
            "/api/conversations/conv-1",
            json={
                "title": "Research Notes",
                "favorite": True,
                "archived": True,
                "pinned": True,
                "tags": ["planning", "Planning", " api  ", ""],
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["title"], "Research Notes")
        self.assertTrue(data["favorite"])
        self.assertTrue(data["archived"])
        self.assertTrue(data["pinned"])
        self.assertEqual(data["tags"], ["planning", "api"])
        self.assertTrue(data["updated_at"])

        stored = storage.get_conversation("conv-1")
        self.assertEqual(stored["tags"], ["planning", "api"])

    def test_list_includes_metadata_and_orders_pinned_first(self):
        self.client.patch("/api/conversations/conv-2", json={"title": "Later"})
        self.client.patch("/api/conversations/conv-1", json={"title": "Pinned", "pinned": True})

        response = self.client.get("/api/conversations")

        self.assertEqual(response.status_code, 200)
        conversations = response.json()
        self.assertEqual(conversations[0]["id"], "conv-1")
        self.assertTrue(conversations[0]["pinned"])
        self.assertIn("favorite", conversations[0])
        self.assertIn("archived", conversations[0])
        self.assertIn("tags", conversations[0])
        self.assertIn("updated_at", conversations[0])

    def test_rejects_empty_title(self):
        response = self.client.patch("/api/conversations/conv-1", json={"title": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Title cannot be empty")

    def test_missing_conversation_returns_404(self):
        response = self.client.patch("/api/conversations/missing", json={"favorite": True})

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
