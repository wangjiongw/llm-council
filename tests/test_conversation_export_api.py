import tempfile
import unittest
from urllib.parse import quote

from fastapi.testclient import TestClient

from backend.main import app
from backend import storage


class ConversationExportAPITest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def save_fixture(self, conversation_id, title, messages):
        conversation = storage.create_conversation(conversation_id)
        conversation["title"] = title
        conversation["messages"] = messages
        storage.save_conversation(conversation)
        return conversation

    def assert_markdown_export_ok(self, conversation_id, title):
        response = self.client.get(f"/api/conversations/{conversation_id}/export?format=markdown")

        self.assertEqual(response.status_code, 200)
        disposition = response.headers["content-disposition"]
        self.assertIn('filename="', disposition)
        self.assertIn("filename*=UTF-8''", disposition)
        safe_title = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in title).strip("-") or "conversation"
        self.assertIn(quote(f"{safe_title}.md", safe=""), disposition)
        self.assertIn(f"# {title}", response.text)
        self.assertIn("## Conversation summary", response.text)
        self.assertIn("## Transcript", response.text)
        self.assertIn("## Turn 1", response.text)
        return response

    def test_exports_quick_council_unicode_interrupted_and_dirty_conversations(self):
        fixtures = [
            (
                "quick",
                "Quick Export",
                [
                    {"role": "user", "content": "Quick question"},
                    {"role": "assistant", "metadata": {"mode": "quick"}, "stage3": {"response": "Quick answer", "status": "success"}},
                ],
                ["Quick question", "Quick answer", "Mode: quick"],
            ),
            (
                "council",
                "Council Export",
                [
                    {"role": "user", "content": "Council question"},
                    {
                        "role": "assistant",
                        "metadata": {"mode": "council"},
                        "stage1": [{"model": "a", "response": "Stage one", "status": "success"}],
                        "stage2": [{"model": "b", "ranking": "Stage two", "status": "success"}],
                        "stage3": {"response": "Final synthesis", "status": "success", "model": "chair"},
                    },
                ],
                ["Stage 1: 1/1 completed", "Stage 2: 1/1 completed", "Final synthesis"],
            ),
            (
                "unicode",
                "变压器DGA跨域预测",
                [
                    {"role": "user", "content": "中文导出问题"},
                    {"role": "assistant", "stage3": {"response": "中文导出回答", "status": "success"}},
                ],
                ["中文导出问题", "中文导出回答"],
            ),
            (
                "interrupted",
                "Interrupted Export",
                [
                    {"role": "user", "content": "Will this finish?"},
                    {"role": "assistant", "status": "interrupted", "stage1": [], "stage2": [], "stage3": None, "error": "Client disconnected"},
                ],
                ["Status: interrupted", "No final response was saved", "Client disconnected"],
            ),
            (
                "dirty",
                "Dirty History Export",
                [
                    {"role": "user", "content": None},
                    {"role": "assistant", "stage1": None, "stage2": None, "stage3": None},
                    {"role": "assistant"},
                ],
                ["[No text content]", "Status: incomplete", "No final response was saved"],
            ),
        ]

        for conversation_id, title, messages, expected_fragments in fixtures:
            with self.subTest(conversation_id=conversation_id):
                self.save_fixture(conversation_id, title, messages)
                response = self.assert_markdown_export_ok(conversation_id, title)
                for fragment in expected_fragments:
                    self.assertIn(fragment, response.text)


if __name__ == "__main__":
    unittest.main()
