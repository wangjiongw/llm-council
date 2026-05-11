import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


class FileUploadApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def test_update_file_queue_accepts_object_body(self):
        response = self.client.patch(
            "/api/conversations/conv-1/file_queue",
            json={
                "files": [
                    {
                        "id": "file-1",
                        "name": "chart.png",
                        "type": "image/png",
                        "size": 12,
                        "category": "image",
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})
        self.assertEqual(storage.get_file_queue("conv-1")[0]["id"], "file-1")

    def test_accepts_text_file_and_sends_extracted_text_to_council(self):
        council_mock = AsyncMock(return_value=([{"model": "a"}], [], {"response": "ok"}, {}))

        with (
            patch("backend.main.run_full_council_with_history", new=council_mock),
            patch(
                "backend.main.generate_conversation_title",
                new=AsyncMock(return_value="Uploaded notes"),
            ),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "summarize this"},
                files={"files": ("notes.md", b"# Plan\n\nShip upload support.", "text/markdown")},
            )

        self.assertEqual(response.status_code, 200)
        content_array = council_mock.call_args.args[0]
        self.assertEqual(content_array[0], {"type": "text", "text": "summarize this"})
        self.assertIn("[Attached file: notes.md]", content_array[1]["text"])
        self.assertIn("Ship upload support.", content_array[1]["text"])

    def test_rejects_unsupported_file_type(self):
        response = self.client.post(
            "/api/conversations/conv-1/message/files",
            data={"content": "please read this"},
            files={"files": ("binary.bin", b"hello", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_successful_upload_clears_pending_file_queue(self):
        storage.update_file_queue(
            "conv-1",
            [
                {
                    "id": "pending-1",
                    "name": "chart.png",
                    "type": "image/png",
                    "size": 12,
                    "category": "image",
                }
            ],
        )

        with (
            patch(
                "backend.main.run_full_council_with_history",
                new=AsyncMock(return_value=([{"model": "a"}], [], {"response": "ok"}, {})),
            ),
            patch(
                "backend.main.generate_conversation_title",
                new=AsyncMock(return_value="Uploaded image"),
            ),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "what is in this image?"},
                files={"files": ("chart.png", b"fake-image", "image/png")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["file_queue"], [])
        self.assertEqual(storage.get_file_queue("conv-1"), [])

        conversation = storage.get_conversation("conv-1")
        self.assertEqual(conversation["title"], "Uploaded image")
        self.assertEqual(conversation["messages"][0]["files"][0]["name"], "chart.png")


if __name__ == "__main__":
    unittest.main()
