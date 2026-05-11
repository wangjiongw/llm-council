import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import storage
from backend import llm_settings
from backend.main import app


class LLMSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        self.original_settings_path = llm_settings.SETTINGS_PATH
        storage.DATA_DIR = self.tmpdir.name
        llm_settings.SETTINGS_PATH = llm_settings.Path(self.tmpdir.name) / "llm_settings.json"
        self.client = TestClient(app)

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        llm_settings.SETTINGS_PATH = self.original_settings_path
        self.tmpdir.cleanup()

    def test_settings_update_redacts_keys_and_resolves_model_override(self):
        response = self.client.patch(
            "/api/settings/llm",
            json={
                "default_provider": {
                    "base_url": "https://default.example/v1",
                    "api_key": "default-key",
                },
                "council_models": ["model-a", "model-b"],
                "model_overrides": {
                    "model-b": {
                        "base_url": "https://override.example/v1",
                        "api_key": "override-key",
                    }
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["default_provider"]["api_key_set"])
        self.assertNotIn("api_key", payload["default_provider"])
        self.assertTrue(payload["model_overrides"]["model-b"]["api_key_set"])

        default_config = llm_settings.resolve_model_config("model-a")
        override_config = llm_settings.resolve_model_config("model-b")
        self.assertEqual(default_config["chat_url"], "https://default.example/v1/chat/completions")
        self.assertEqual(override_config["chat_url"], "https://override.example/v1/chat/completions")

    def test_quick_query_uses_fallback_after_primary_failure(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "quick_model": "primary-model",
            "quick_fallback_models": ["fallback-model"],
        })

        async def fake_query(model, messages, timeout=120.0):
            if model == "primary-model":
                return None
            return {"model": model, "content": "fallback ok", "usage": {}}

        async def run_query():
            from backend.council import quick_query

            return await quick_query("hello")

        import asyncio
        with patch("backend.openrouter.query_model", new=AsyncMock(side_effect=fake_query)):
            result = asyncio.run(run_query())

        self.assertEqual(result["model"], "fallback-model")
        self.assertEqual(result["response"], "fallback ok")
        self.assertEqual(
            result["metadata"]["attempts"],
            [
                {"model": "primary-model", "ok": False},
                {"model": "fallback-model", "ok": True},
            ],
        )

    def test_history_context_excludes_current_message_and_stores_summary(self):
        storage.create_conversation("conv-1")

        for i in range(22):
            storage.add_user_message("conv-1", f"user {i}")
            storage.add_assistant_message(
                "conv-1",
                [],
                [],
                {"response": f"assistant {i}"},
            )

        with (
            patch("backend.main.generate_conversation_title", new=AsyncMock(return_value="Title")),
            patch(
                "backend.main.run_full_council_with_history",
                new=AsyncMock(return_value=([{"model": "a"}], [], {"response": "ok"}, {})),
            ) as council_mock,
            patch(
                "backend.storage.summarize_conversation_segment",
                new=AsyncMock(return_value="older summary"),
            ),
        ):
            response = self.client.post(
                "/api/conversations/conv-1/message",
                json={"content": "current question"},
            )

        self.assertEqual(response.status_code, 200)
        conversation_history = council_mock.call_args.args[1]
        self.assertNotIn("current question", str(conversation_history))
        self.assertEqual(conversation_history[0]["role"], "system")
        self.assertIn("older summary", conversation_history[0]["content"])

        conversation = storage.get_conversation("conv-1")
        self.assertEqual(conversation["context_summary"]["content"], "older summary")


if __name__ == "__main__":
    unittest.main()
