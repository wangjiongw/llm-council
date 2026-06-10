import tempfile
import unittest
from unittest.mock import AsyncMock, patch

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

        self.assertEqual(data["title_source"], "manual")
        self.assertFalse(data["title_locked"])
        self.assertTrue(data["title_updated_at"])

    def test_manual_title_locks_against_automatic_llm_updates(self):
        response = self.client.patch(
            "/api/conversations/conv-1",
            json={"title": "Manual Research Title", "title_source": "manual", "title_locked": True},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["title"], "Manual Research Title")
        self.assertEqual(data["title_source"], "manual")
        self.assertTrue(data["title_locked"])
        self.assertTrue(data["title_updated_at"])

        skipped = storage.update_conversation_title(
            "conv-1",
            "Automatic LLM Title",
            source="llm",
            locked=False,
            respect_lock=True,
        )
        self.assertEqual(skipped["title"], "Manual Research Title")
        self.assertEqual(skipped["title_source"], "manual")
        self.assertTrue(skipped["title_locked"])

        applied = storage.update_conversation_title(
            "conv-1",
            "Explicit AI Title",
            source="llm",
            locked=False,
            respect_lock=False,
        )
        self.assertEqual(applied["title"], "Explicit AI Title")
        self.assertEqual(applied["title_source"], "llm")
        self.assertFalse(applied["title_locked"])

    def test_list_includes_metadata_and_orders_pinned_first(self):
        self.client.patch("/api/conversations/conv-2", json={"title": "Later"})
        self.client.patch("/api/conversations/conv-1", json={"title": "Pinned", "pinned": True})
        conversation = storage.get_conversation("conv-1")
        conversation["messages"] = [
            {"role": "user", "content": "First question", "files": [{"name": "notes.txt"}], "pinned": True},
            {"role": "assistant", "stage3": {"response": "First answer"}},
            {"role": "user", "content": "Second question"},
            {"role": "assistant", "status": "failed", "stage3": {"status": "failed", "error": "provider failed"}},
        ]
        conversation["context_memory"] = [{"id": "mem-1", "content": "Remember this.", "enabled": True}]
        storage.save_conversation(conversation)

        response = self.client.get("/api/conversations")

        self.assertEqual(response.status_code, 200)
        conversations = response.json()
        self.assertEqual(conversations[0]["id"], "conv-1")
        self.assertTrue(conversations[0]["pinned"])
        self.assertIn("favorite", conversations[0])
        self.assertIn("archived", conversations[0])
        self.assertIn("tags", conversations[0])
        self.assertIn("updated_at", conversations[0])
        self.assertEqual(conversations[0]["message_count"], 4)
        self.assertEqual(conversations[0]["turn_count"], 2)
        self.assertTrue(conversations[0]["has_files"])
        self.assertTrue(conversations[0]["has_failed_run"])
        self.assertTrue(conversations[0]["has_memory"])
        self.assertEqual(conversations[0]["pinned_message_count"], 1)

    def test_rejects_empty_title(self):
        response = self.client.patch("/api/conversations/conv-1", json={"title": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Title cannot be empty")

    def test_batch_updates_conversation_metadata(self):
        response = self.client.patch(
            "/api/conversations/batch",
            json={
                "conversation_ids": ["conv-1", "conv-2"],
                "updates": {"favorite": True, "archived": True, "tags": ["work"]},
                "tag_mode": "add",
            },
        )

        self.assertEqual(response.status_code, 200)
        conversations = response.json()["conversations"]
        self.assertEqual({item["id"] for item in conversations}, {"conv-1", "conv-2"})
        self.assertTrue(all(item["favorite"] for item in conversations))
        self.assertTrue(all(item["archived"] for item in conversations))
        self.assertEqual(storage.get_conversation("conv-1")["tags"], ["work"])

        response = self.client.patch(
            "/api/conversations/batch",
            json={
                "conversation_ids": ["conv-1"],
                "updates": {"tags": ["work"]},
                "tag_mode": "remove",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversations"][0]["tags"], [])

    def test_management_tag_colors_and_saved_views(self):
        color_response = self.client.post(
            "/api/conversations/tag-colors",
            json={"tag": "context", "color": "#123abc"},
        )

        self.assertEqual(color_response.status_code, 200)
        self.assertEqual(color_response.json()["tag_colors"]["context"], "#123abc")

        view_response = self.client.post(
            "/api/conversations/saved-views",
            json={"name": "Active context", "filters": {"viewMode": "active", "tagFilter": "context", "searchFlags": {"favoriteOnly": True, "taggedOnly": True}}},
        )

        self.assertEqual(view_response.status_code, 200)
        saved_views = view_response.json()["saved_views"]
        self.assertEqual(saved_views[0]["name"], "Active context")
        self.assertEqual(saved_views[0]["filters"]["tagFilter"], "context")
        self.assertTrue(saved_views[0]["filters"]["searchFlags"]["favoriteOnly"])
        self.assertTrue(saved_views[0]["filters"]["searchFlags"]["taggedOnly"])

        management_response = self.client.get("/api/conversations/management")
        self.assertEqual(management_response.status_code, 200)
        self.assertEqual(management_response.json()["saved_views"][0]["name"], "Active context")

        delete_response = self.client.delete(f"/api/conversations/saved-views/{saved_views[0]['id']}")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["saved_views"], [])

    def test_export_and_title_suggestions(self):
        conversation = storage.get_conversation("conv-1")
        conversation["title"] = "Initial Notes"
        conversation["tags"] = ["planning"]
        conversation["messages"] = [
            {"role": "user", "content": "Design saved views for conversation management"},
            {"role": "assistant", "stage3": {"response": "Use filters and persisted view metadata."}},
            {"role": "user", "content": "What if a run is interrupted?"},
            {"role": "assistant", "status": "interrupted", "stage1": [], "stage2": [], "stage3": None, "error": "Client disconnected"},
        ]
        storage.save_conversation(conversation)

        export_response = self.client.get("/api/conversations/conv-1/export?format=markdown")
        self.assertEqual(export_response.status_code, 200)
        self.assertIn("# Initial Notes", export_response.text)
        self.assertIn("## Conversation summary", export_response.text)
        self.assertIn("## Turn 1", export_response.text)
        self.assertIn("Design saved views", export_response.text)
        self.assertIn("Use filters", export_response.text)
        self.assertIn("Status: interrupted", export_response.text)
        self.assertIn("No final response was saved", export_response.text)

        conversation["title"] = "中文标题"
        storage.save_conversation(conversation)
        unicode_export_response = self.client.get("/api/conversations/conv-1/export?format=markdown")
        self.assertEqual(unicode_export_response.status_code, 200)
        self.assertIn("# 中文标题", unicode_export_response.text)
        self.assertIn("filename*=UTF-8''%E4%B8%AD%E6%96%87%E6%A0%87%E9%A2%98.md", unicode_export_response.headers["content-disposition"])

        with patch("backend.main.generate_conversation_title_from_context", new=AsyncMock(return_value="Conversation Views Design")) as mock_title:
            title_response = self.client.post("/api/conversations/conv-1/title-suggestions")

        self.assertEqual(title_response.status_code, 200)
        payload = title_response.json()
        suggestions = payload["suggestions"]
        self.assertEqual(payload["source"], "llm")
        self.assertEqual(suggestions[0], "Conversation Views Design")
        self.assertTrue(mock_title.await_count >= 1)

    def test_title_suggestions_fall_back_when_llm_title_fails(self):
        conversation = storage.get_conversation("conv-1")
        conversation["messages"] = [
            {"role": "user", "content": "Summarize council fallback behavior for partial model failures"},
            {"role": "assistant", "stage3": {"response": "Use successful model outputs and report failed models."}},
        ]
        storage.save_conversation(conversation)

        with patch("backend.main.generate_conversation_title_from_context", new=AsyncMock(side_effect=RuntimeError("provider unavailable"))):
            response = self.client.post("/api/conversations/conv-1/title-suggestions")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "local")
        self.assertTrue(payload["suggestions"])
        self.assertIn("council", payload["suggestions"][0].lower())

    def test_local_title_suggestions_compact_long_cjk_text(self):
        conversation = storage.get_conversation("conv-1")
        conversation["messages"] = [
            {"role": "user", "content": "请详细分析这个非常非常长的需求描述其中包含很多没有空格的中文文本用于验证本地标题不会把整段内容都塞进侧栏标题显示区域"},
        ]
        storage.save_conversation(conversation)

        suggestions = storage.suggest_conversation_titles("conv-1")

        self.assertTrue(suggestions)
        self.assertLessEqual(len(suggestions[0]), 45)
        self.assertTrue(suggestions[0].endswith("..."))

    def test_missing_conversation_returns_404(self):
        response = self.client.patch("/api/conversations/missing", json={"favorite": True})

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
