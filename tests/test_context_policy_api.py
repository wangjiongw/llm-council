import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextPolicyApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_get_context_policy_returns_defaults(self):
        response = self.client.get("/api/conversations/conv-1/context-policy")

        self.assertEqual(response.status_code, 200)
        policy = response.json()
        self.assertEqual(policy["token_budget"], 24000)
        self.assertEqual(policy["recent_turns"], 10)
        self.assertTrue(policy["summarize_older"])
        self.assertTrue(policy["use_pinned"])
        self.assertTrue(policy["use_memory"])
        self.assertEqual(policy["memory_max_chars"], 8000)

    def test_patch_context_policy_updates_and_clamps_values(self):
        response = self.client.patch(
            "/api/conversations/conv-1/context-policy",
            json={
                "token_budget": 500,
                "recent_turns": 3,
                "summarize_older": False,
                "use_pinned": False,
                "pin_max_chars": 999999,
                "use_memory": False,
                "memory_max_chars": 999999,
            },
        )

        self.assertEqual(response.status_code, 200)
        policy = response.json()["context_policy"]
        self.assertEqual(policy["token_budget"], 1000)
        self.assertEqual(policy["recent_turns"], 3)
        self.assertFalse(policy["summarize_older"])
        self.assertFalse(policy["use_pinned"])
        self.assertEqual(policy["pin_max_chars"], 120000)
        self.assertFalse(policy["use_memory"])
        self.assertEqual(policy["memory_max_chars"], 120000)

        audit = self.client.get("/api/conversations/conv-1/context").json()
        self.assertEqual(audit["context_policy"], policy)

    def test_context_policy_unknown_conversation_returns_404(self):
        response = self.client.get("/api/conversations/missing/context-policy")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
