import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from backend import llm_settings


class CouncilFailureStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_settings_path = llm_settings.SETTINGS_PATH
        llm_settings.SETTINGS_PATH = llm_settings.Path(self.tmpdir.name) / "llm_settings.json"

    def tearDown(self):
        llm_settings.SETTINGS_PATH = self.original_settings_path
        self.tmpdir.cleanup()

    def test_stage1_records_failed_models_instead_of_dropping_them(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "council_models": ["fast-model", "slow-model"],
        })

        async def fake_parallel(models, messages):
            return {
                "fast-model": {
                    "status": "success",
                    "model": "fast-model",
                    "content": "fast answer",
                    "usage": {},
                    "duration_seconds": 1.2,
                },
                "slow-model": {
                    "status": "failed",
                    "model": "slow-model",
                    "error_type": "timeout",
                    "error": "Request timed out after 120.0 seconds",
                    "timeout_seconds": 120.0,
                    "duration_seconds": 120.1,
                },
            }

        async def run_stage1():
            from backend.council import stage1_collect_responses_with_history

            return await stage1_collect_responses_with_history("hello")

        with patch("backend.council.query_models_parallel", new=AsyncMock(side_effect=fake_parallel)):
            results = asyncio.run(run_stage1())

        self.assertEqual([result["model"] for result in results], ["fast-model", "slow-model"])
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[0]["response"], "fast answer")
        self.assertEqual(results[1]["status"], "failed")
        self.assertEqual(results[1]["error_type"], "timeout")
        self.assertNotIn("response", results[1])

    def test_stage2_prompt_excludes_failed_stage1_records(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "council_models": ["judge-model"],
        })

        captured_messages = {}

        async def fake_parallel(models, messages):
            captured_messages["messages"] = messages
            return {
                "judge-model": {
                    "status": "success",
                    "model": "judge-model",
                    "content": "FINAL RANKING:\n1. Response A",
                    "usage": {},
                }
            }

        stage1_results = [
            {"model": "fast-model", "status": "success", "response": "good answer"},
            {
                "model": "slow-model",
                "status": "failed",
                "error_type": "timeout",
                "error": "Request timed out after 120.0 seconds",
            },
        ]

        async def run_stage2():
            from backend.council import stage2_collect_rankings_with_history

            return await stage2_collect_rankings_with_history("hello", stage1_results)

        with patch("backend.council.query_models_parallel", new=AsyncMock(side_effect=fake_parallel)):
            stage2_results, label_to_model = asyncio.run(run_stage2())

        prompt = captured_messages["messages"][0]["content"]
        self.assertIn("Response A", prompt)
        self.assertIn("good answer", prompt)
        self.assertNotIn("slow-model", prompt)
        self.assertNotIn("Request timed out", prompt)
        self.assertEqual(label_to_model, {"Response A": "fast-model"})
        self.assertEqual(stage2_results[0]["status"], "success")

    def test_resolve_model_config_supports_default_and_override_timeout(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {
                "base_url": "https://default.example/v1",
                "api_key": "default-key",
                "timeout": 180,
                "stream": True,
            },
            "model_overrides": {
                "slow-model": {"timeout": 600, "stream": False},
            },
        })

        self.assertEqual(llm_settings.resolve_model_config("fast-model")["timeout"], 180.0)
        self.assertEqual(llm_settings.resolve_model_config("slow-model")["timeout"], 600.0)
        self.assertTrue(llm_settings.resolve_model_config("fast-model")["stream"])
        self.assertFalse(llm_settings.resolve_model_config("slow-model")["stream"])

    def test_query_model_returns_failure_record_for_disabled_model(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {
                "base_url": "https://default.example/v1",
                "api_key": "default-key",
            },
            "model_overrides": {
                "disabled-model": {"enabled": False},
            },
        })

        async def run_query():
            from backend.openrouter import query_model

            return await query_model("disabled-model", [{"role": "user", "content": "hello"}])

        result = asyncio.run(run_query())

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_type"], "disabled_model")
        self.assertIn("disabled", result["error"])


if __name__ == "__main__":
    unittest.main()
