import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class ContextPinApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")
        storage.add_user_message("conv-1", "important instruction")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_pin_and_unpin_message(self):
        response = self.client.patch(
            "/api/conversations/conv-1/messages/0/pin",
            json={"pinned": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["pinned"])
        self.assertTrue(payload["conversation"]["messages"][0]["pinned"])
        self.assertIn("pinned_at", payload["conversation"]["messages"][0])

        response = self.client.patch(
            "/api/conversations/conv-1/messages/0/pin",
            json={"pinned": False},
        )

        self.assertEqual(response.status_code, 200)
        message = response.json()["conversation"]["messages"][0]
        self.assertFalse(message["pinned"])
        self.assertNotIn("pinned_at", message)

    def test_pin_message_rejects_invalid_message_index(self):
        response = self.client.patch(
            "/api/conversations/conv-1/messages/9/pin",
            json={"pinned": True},
        )

        self.assertEqual(response.status_code, 400)

    def test_pin_message_unknown_conversation_returns_404(self):
        response = self.client.patch(
            "/api/conversations/missing/messages/0/pin",
            json={"pinned": True},
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
