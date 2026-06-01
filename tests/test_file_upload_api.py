import os
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
        self.original_env = {
            key: os.environ.get(key)
            for key in (
                "FILE_CONTEXT_MAX_CHARS",
                "FILE_CONTEXT_CHUNK_CHARS",
                "FILE_CONTEXT_MAX_CHUNKS",
            )
        }
        self.client = TestClient(app)
        storage.create_conversation("conv-1")

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

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


    def test_quick_mode_with_file_uses_quick_query(self):
        quick_mock = AsyncMock(return_value={
            "model": "quick-model",
            "status": "success",
            "response": "quick file ok",
            "metadata": {"attempts": [{"model": "quick-model", "ok": True}]},
        })
        council_mock = AsyncMock(return_value=([{}], [], {"response": "wrong path"}, {}))

        with (
            patch("backend.main.quick_query", new=quick_mock),
            patch("backend.main.run_full_council_with_history", new=council_mock),
            patch(
                "backend.main.generate_conversation_title",
                new=AsyncMock(return_value="Quick upload"),
            ),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "answer from this file", "mode": "quick"},
                files={"files": ("notes.md", b"Important context", "text/markdown")},
            )

        self.assertEqual(response.status_code, 200)
        council_mock.assert_not_awaited()
        quick_mock.assert_awaited_once()
        content_array = quick_mock.call_args.args[0]
        self.assertEqual(content_array[0], {"type": "text", "text": "answer from this file"})
        self.assertIn("Important context", content_array[1]["text"])

        payload = response.json()
        self.assertEqual(payload["stage1_results"], [])
        self.assertEqual(payload["stage2_results"], [])
        self.assertEqual(payload["stage3_result"]["response"], "quick file ok")
        self.assertEqual(payload["metadata"]["mode"], "quick")
        self.assertEqual(payload["metadata"]["attempts"], [{"model": "quick-model", "ok": True}])

        conversation = storage.get_conversation("conv-1")
        self.assertEqual(conversation["messages"][0]["role"], "user")
        self.assertEqual(conversation["messages"][1]["metadata"]["mode"], "quick")
        self.assertEqual(conversation["messages"][1]["stage1"], [])
        self.assertEqual(conversation["messages"][1]["stage2"], [])
        self.assertEqual(len(conversation["turns"]), 1)
        turn = conversation["turns"][0]
        self.assertEqual(turn["mode"], "quick")
        self.assertEqual(turn["status"], "complete")
        self.assertEqual(turn["context_snapshot"]["current_turn"]["text_attachment_count"], 1)
        self.assertEqual(turn["context_snapshot"]["current_turn"]["file_names"], ["notes.md"])
        self.assertEqual(turn["runs"][0]["stage"], "stage3")
        self.assertEqual(turn["runs"][0]["model"], "quick-model")


    def test_image_upload_is_sent_to_model_but_redacted_from_persistent_context_audit(self):
        quick_mock = AsyncMock(return_value={
            "model": "quick-model",
            "status": "success",
            "response": "image ok",
            "metadata": {"attempts": [{"model": "quick-model", "ok": True}]},
        })

        with (
            patch("backend.main.quick_query", new=quick_mock),
            patch("backend.main.generate_conversation_title", new=AsyncMock(return_value="Image upload")),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "describe this image", "mode": "quick"},
                files={"files": ("chart.png", b"fake-image-bytes", "image/png")},
            )

        self.assertEqual(response.status_code, 200)
        model_content = quick_mock.call_args.args[0]
        self.assertEqual(model_content[0], {"type": "text", "text": "describe this image"})
        self.assertEqual(model_content[1]["type"], "image_url")
        self.assertTrue(model_content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

        conversation = storage.get_conversation("conv-1")
        conversation = storage.get_conversation("conv-1")
        stored_content = conversation["messages"][0]["content"]
        self.assertEqual(stored_content[1]["image_url"], {"url": "[redacted image data URI]", "redacted": True})
        self.assertIn("attachment_ref", stored_content[1])
        self.assertNotIn("data:image/png;base64", str(stored_content))
        self.assertEqual(conversation["messages"][0]["files"][0]["name"], "chart.png")
        self.assertEqual(conversation["messages"][0]["files"][0]["attachment_id"], stored_content[1]["attachment_ref"]["id"])
        attachment_path = os.path.join(
            storage.DATA_DIR,
            "attachments",
            "conv-1",
            stored_content[1]["attachment_ref"]["id"],
        )
        self.assertTrue(os.path.exists(attachment_path))

        context_payload = conversation["turns"][0]["context_payload"]
        self.assertTrue(context_payload["compaction"]["compacted"])
        self.assertEqual(context_payload["compaction"]["redacted_image_items"], 1)
        self.assertNotIn("data:image/png;base64", str(context_payload))
        self.assertEqual(
            context_payload["current_message"]["content"][1]["image_url"],
            {"url": "[redacted image data URI]", "redacted": True},
        )
        self.assertEqual(
            context_payload["current_message"]["content"][1]["attachment_ref"]["id"],
            stored_content[1]["attachment_ref"]["id"],
        )

        retry_mock = AsyncMock(return_value={
            "model": "quick-model",
            "status": "success",
            "response": "image retry ok",
            "metadata": {"attempts": [{"model": "quick-model", "ok": True}]},
        })
        with patch("backend.main.quick_query", new=retry_mock):
            retry = self.client.post(
                "/api/conversations/conv-1/messages/0/retry",
                json={"mode": "quick"},
            )

        self.assertEqual(retry.status_code, 200)
        retry_content = retry_mock.call_args.args[0]
        self.assertTrue(retry_content[1]["image_url"]["url"].startswith("data:image/png;base64,"))


    def test_image_attachment_lifecycle_copies_to_branch_and_cleans_deleted_conversation(self):
        quick_mock = AsyncMock(return_value={
            "model": "quick-model",
            "status": "success",
            "response": "image ok",
            "metadata": {"attempts": [{"model": "quick-model", "ok": True}]},
        })

        with (
            patch("backend.main.quick_query", new=quick_mock),
            patch("backend.main.generate_conversation_title", new=AsyncMock(return_value="Image upload")),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "describe this image", "mode": "quick"},
                files={"files": ("chart.png", b"fake-image-bytes", "image/png")},
            )

        self.assertEqual(response.status_code, 200)
        parent = storage.get_conversation("conv-1")
        parent_ref = parent["messages"][0]["content"][1]["attachment_ref"]
        parent_path = os.path.join(storage.DATA_DIR, "attachments", "conv-1", parent_ref["id"])
        self.assertTrue(os.path.exists(parent_path))

        branch_response = self.client.post(
            "/api/conversations/conv-1/fork",
            json={"message_index": 1},
        )

        self.assertEqual(branch_response.status_code, 200)
        branch = branch_response.json()
        branch_ref = branch["messages"][0]["content"][1]["attachment_ref"]
        self.assertEqual(branch_ref["conversation_id"], branch["id"])
        self.assertEqual(branch_ref["id"], parent_ref["id"])
        branch_path = os.path.join(storage.DATA_DIR, "attachments", branch["id"], branch_ref["id"])
        self.assertTrue(os.path.exists(branch_path))
        self.assertTrue(os.path.exists(parent_path))

        self.client.delete(f"/api/conversations/{branch['id']}")
        self.assertFalse(os.path.exists(os.path.dirname(branch_path)))
        self.assertTrue(os.path.exists(parent_path))

    def test_truncate_removes_unreferenced_image_attachment(self):
        quick_mock = AsyncMock(return_value={
            "model": "quick-model",
            "status": "success",
            "response": "image ok",
            "metadata": {"attempts": [{"model": "quick-model", "ok": True}]},
        })

        with (
            patch("backend.main.quick_query", new=quick_mock),
            patch("backend.main.generate_conversation_title", new=AsyncMock(return_value="Image upload")),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "describe this image", "mode": "quick"},
                files={"files": ("chart.png", b"fake-image-bytes", "image/png")},
            )

        self.assertEqual(response.status_code, 200)
        conversation = storage.get_conversation("conv-1")
        attachment_id = conversation["messages"][0]["content"][1]["attachment_ref"]["id"]
        attachment_path = os.path.join(storage.DATA_DIR, "attachments", "conv-1", attachment_id)
        self.assertTrue(os.path.exists(attachment_path))

        truncate = self.client.delete("/api/conversations/conv-1/messages/from/0")

        self.assertEqual(truncate.status_code, 200)
        self.assertFalse(os.path.exists(attachment_path))


    def test_long_text_file_selects_relevant_chunks_for_context_budget(self):
        os.environ["FILE_CONTEXT_MAX_CHARS"] = "1200"
        os.environ["FILE_CONTEXT_CHUNK_CHARS"] = "500"
        os.environ["FILE_CONTEXT_MAX_CHUNKS"] = "2"
        quick_mock = AsyncMock(return_value={
            "model": "quick-model",
            "status": "success",
            "response": "selected file ok",
            "metadata": {"attempts": [{"model": "quick-model", "ok": True}]},
        })
        long_text = (
            "alpha introduction " + ("ordinary filler " * 80) +
            "\n\nneedle target policy appears here with the answer " + ("relevant detail " * 20) +
            "\n\nomega appendix " + ("unrelated tail " * 120)
        )

        with (
            patch("backend.main.quick_query", new=quick_mock),
            patch("backend.main.generate_conversation_title", new=AsyncMock(return_value="Long upload")),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "find the needle target policy", "mode": "quick"},
                files={"files": ("long-notes.md", long_text.encode(), "text/markdown")},
            )

        self.assertEqual(response.status_code, 200)
        content_array = quick_mock.call_args.args[0]
        attached_text = content_array[1]["text"]
        self.assertIn("needle target policy", attached_text)
        self.assertIn("Selected 2 of", attached_text)
        self.assertLess(len(attached_text), len(long_text))
        self.assertEqual(content_array[1]["file_context"]["strategy"], "query_relevant_chunks_v1")

        conversation = storage.get_conversation("conv-1")
        current_turn = conversation["turns"][0]["context_snapshot"]["current_turn"]
        self.assertEqual(current_turn["file_contexts"][0]["filename"], "long-notes.md")
        self.assertEqual(current_turn["file_contexts"][0]["selected_chunks"], 2)

    def test_rejects_invalid_file_message_mode_before_model_call(self):
        council_mock = AsyncMock()
        quick_mock = AsyncMock()

        with (
            patch("backend.main.run_full_council_with_history", new=council_mock),
            patch("backend.main.quick_query", new=quick_mock),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message/files",
                data={"content": "hello", "mode": "fast"},
                files={"files": ("notes.md", b"Important context", "text/markdown")},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("mode must be", response.json()["detail"])
        council_mock.assert_not_awaited()
        quick_mock.assert_not_awaited()
        self.assertEqual(storage.get_conversation("conv-1")["messages"], [])

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
