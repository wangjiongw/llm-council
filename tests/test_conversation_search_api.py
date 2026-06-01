import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ConversationSearchApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)

        storage.create_conversation("conv-1")
        storage.update_conversation_title("conv-1", "Context design notes")
        storage.add_user_message("conv-1", "How should a stateless model API receive history?")
        storage.add_assistant_message(
            "conv-1",
            [],
            [],
            {"model": "m", "status": "success", "response": "The server owns context assembly before each request."},
            metadata={"mode": "quick"},
        )

        storage.create_conversation("conv-2")
        storage.update_conversation_title("conv-2", "Deployment notes")
        storage.add_context_memory("conv-2", "Durable memory says API calls are stateless.")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_search_conversations_returns_message_and_memory_matches(self):
        response = self.client.get("/api/conversations/search", params={"q": "stateless", "limit": 10})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["query"], "stateless")
        sources = {(result["conversation_id"], result["source"]) for result in payload["results"]}
        self.assertIn(("conv-1", "message"), sources)
        self.assertIn(("conv-2", "memory"), sources)
        self.assertTrue(all("excerpt" in result for result in payload["results"]))

    def test_search_conversations_can_find_assistant_final_response(self):
        response = self.client.get("/api/conversations/search", params={"q": "assembly", "limit": 5})

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        assistant_matches = [result for result in results if result["role"] == "assistant"]
        self.assertEqual(assistant_matches[0]["conversation_id"], "conv-1")
        self.assertEqual(assistant_matches[0]["message_index"], 1)
        self.assertIn("server owns context", assistant_matches[0]["content"])

    def test_search_conversations_rejects_empty_query(self):
        response = self.client.get("/api/conversations/search", params={"q": "   "})

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
