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

    def test_provider_diagnostics_redacts_secrets_and_reports_model_readiness(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {
                "base_url": "https://default.example/v1",
                "api_key": "default-key",
                "timeout": 45,
                "stream": True,
            },
            "council_models": ["model-a", "model-b"],
            "chairman_model": "model-b",
            "quick_model": "model-c",
            "title_model": "",
            "summarization_model": "",
            "model_overrides": {
                "model-b": {
                    "base_url": "https://override.example/v1",
                    "api_key": "override-key",
                    "timeout": 600,
                    "stream": False,
                },
                "model-c": {
                    "api_key": "",
                    "enabled": False,
                },
            },
        })

        response = self.client.get("/api/settings/llm/diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["schema"], "llm_provider_diagnostics_v1")
        self.assertNotIn("default-key", str(payload))
        self.assertNotIn("override-key", str(payload))
        self.assertEqual(payload["checks"]["rate_limit"], "not_checked")

        by_model = {entry["model"]: entry for entry in payload["models"]}
        self.assertEqual(by_model["model-a"]["base_url"], "https://default.example/v1")
        self.assertTrue(by_model["model-a"]["api_key_set"])
        self.assertEqual(by_model["model-b"]["provider_source"], "override")
        self.assertEqual(by_model["model-b"]["timeout"], 600.0)
        self.assertFalse(by_model["model-b"]["stream"])
        self.assertIn("council", by_model["model-b"]["roles"])
        self.assertIn("chairman", by_model["model-b"]["roles"])
        self.assertIn("disabled_model", by_model["model-c"]["problems"])
        self.assertEqual(payload["summary"]["configured_model_count"], 3)
        self.assertEqual(payload["summary"]["problem_model_count"], 1)

    def test_provider_diagnostics_reports_missing_default_provider_config(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {"base_url": "", "api_key": "", "timeout": 0},
            "council_models": ["missing-config-model"],
            "chairman_model": "",
            "quick_model": "",
            "title_model": "",
            "summarization_model": "",
        })

        response = self.client.get("/api/settings/llm/diagnostics")

        self.assertEqual(response.status_code, 200)
        model = response.json()["models"][0]
        self.assertEqual(model["model"], "missing-config-model")
        self.assertEqual(model["problems"], ["missing_base_url", "missing_api_key", "invalid_timeout"])


    def test_llm_settings_test_endpoint_calls_model(self):
        with patch(
            "backend.main.query_model",
            new=AsyncMock(return_value={
                "status": "success",
                "model": "test-model",
                "content": "ok",
                "usage": {"total_tokens": 1},
            }),
        ) as query_mock:
            response = self.client.post(
                "/api/settings/llm/test",
                json={"model": "test-model"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["content"], "ok")
        query_mock.assert_awaited_once()

    def test_provider_diagnostics_probe_calls_model_and_model_list_explicitly(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {
                "base_url": "https://provider.example/v1",
                "api_key": "secret-key",
                "timeout": 45,
                "stream": False,
            },
            "council_models": ["probe-model"],
            "chairman_model": "",
            "quick_model": "",
            "title_model": "",
            "summarization_model": "",
        })

        class FakeModelsResponse:
            status_code = 200
            is_error = False
            text = ""

            def json(self):
                return {"data": [{"id": "probe-model"}, {"id": "other-model"}]}

        class FakeAsyncClient:
            def __init__(self, timeout=None):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                self.requested_url = url
                self.headers = headers or {}
                return FakeModelsResponse()

        with (
            patch("backend.main.query_model", new=AsyncMock(return_value={
                "status": "success",
                "model": "probe-model",
                "content": "ok",
                "duration_seconds": 0.2,
                "usage": {"total_tokens": 2},
            })) as query_mock,
            patch("backend.main.httpx.AsyncClient", new=FakeAsyncClient),
        ):
            response = self.client.post(
                "/api/settings/llm/diagnostics/probe",
                json={"model": "probe-model", "include_model_list": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema"], "llm_provider_probe_v1")
        self.assertTrue(payload["explicit_probe"])
        self.assertTrue(payload["connection"]["ok"])
        self.assertEqual(payload["connection"]["status"], "ok")
        self.assertEqual(payload["rate_limit"]["status"], "not_limited")
        self.assertTrue(payload["model_list"]["ok"])
        self.assertEqual(payload["model_list"]["model_count"], 2)
        self.assertTrue(payload["model_list"]["target_model_found"])
        self.assertNotIn("secret-key", str(payload))
        query_mock.assert_awaited_once()

    def test_provider_diagnostics_probe_reports_rate_limit_without_raising(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {
                "base_url": "https://provider.example/v1",
                "api_key": "secret-key",
                "timeout": 45,
                "stream": False,
            },
            "council_models": ["limited-model"],
            "chairman_model": "",
            "quick_model": "",
            "title_model": "",
            "summarization_model": "",
        })

        with patch("backend.main.query_model", new=AsyncMock(return_value={
            "status": "failed",
            "model": "limited-model",
            "content": None,
            "error_type": "http_status",
            "error": "429 Too Many Requests",
            "status_code": 429,
            "duration_seconds": 0.1,
        })):
            response = self.client.post(
                "/api/settings/llm/diagnostics/probe",
                json={"model": "limited-model", "include_model_list": False},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["connection"]["ok"])
        self.assertEqual(payload["connection"]["status_code"], 429)
        self.assertEqual(payload["rate_limit"]["status"], "limited")
        self.assertEqual(payload["model_list"]["status"], "skipped")
        self.assertNotIn("secret-key", str(payload))

    def test_empty_fallback_lists_use_implicit_nano_without_publicly_configuring_it(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "chairman_fallback_models": [],
            "quick_fallback_models": [],
            "title_fallback_models": [],
            "summarization_fallback_models": [],
        })

        public_settings = llm_settings.public_llm_settings()
        self.assertEqual(public_settings["chairman_fallback_models"], [])
        self.assertEqual(public_settings["quick_fallback_models"], [])
        self.assertEqual(public_settings["title_fallback_models"], [])
        self.assertEqual(public_settings["summarization_fallback_models"], [])
        self.assertEqual(llm_settings.model_list("chairman_fallback_models"), ["gpt-5-nano"])
        self.assertEqual(llm_settings.model_list("quick_fallback_models"), ["gpt-5-nano"])
        self.assertEqual(llm_settings.model_list("title_fallback_models"), ["gpt-5-nano"])
        self.assertEqual(llm_settings.model_list("summarization_fallback_models"), ["gpt-5-nano"])

    def test_configured_fallback_list_overrides_implicit_nano(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "chairman_fallback_models": ["chairman-fallback"],
            "quick_fallback_models": ["custom-fallback"],
        })

        self.assertEqual(llm_settings.model_list("chairman_fallback_models"), ["chairman-fallback"])
        self.assertEqual(llm_settings.model_list("quick_fallback_models"), ["custom-fallback"])

    def test_quick_query_uses_fallback_after_primary_failure(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "quick_model": "primary-model",
            "quick_fallback_models": ["fallback-model"],
        })

        async def fake_query(model, messages, timeout=120.0, event_callback=None):
            if model == "primary-model":
                return None
            return {"model": model, "content": "fallback ok", "usage": {}}

        async def run_query():
            from backend.council import quick_query

            return await quick_query("hello")

        import asyncio
        with patch("backend.council.query_model", new=AsyncMock(side_effect=fake_query)):
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


    def test_stage3_synthesis_uses_fallback_after_primary_failure(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "chairman_model": "primary-chairman",
            "chairman_fallback_models": ["fallback-chairman"],
        })

        async def fake_query(model, messages, event_callback=None):
            if model == "primary-chairman":
                return {"status": "failed", "model": model, "error_type": "timeout", "error": "slow"}
            return {"status": "success", "model": model, "content": "fallback synthesis", "usage": {}}

        async def run_query():
            from backend.council import stage3_synthesize_final

            return await stage3_synthesize_final(
                "hello",
                [{"model": "a", "status": "success", "response": "answer"}],
                [{"model": "b", "status": "success", "ranking": "FINAL RANKING:\n1. Response A"}],
            )

        import asyncio
        with patch("backend.council.query_model", new=AsyncMock(side_effect=fake_query)):
            result = asyncio.run(run_query())

        self.assertEqual(result["model"], "fallback-chairman")
        self.assertEqual(result["response"], "fallback synthesis")
        self.assertEqual(
            result["metadata"]["attempts"],
            [
                {"model": "primary-chairman", "ok": False, "error_type": "timeout", "error": "slow"},
                {"model": "fallback-chairman", "ok": True},
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
            patch("backend.main.generate_initial_title", new=AsyncMock(return_value="Title")),
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
