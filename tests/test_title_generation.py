import unittest
from unittest.mock import AsyncMock, patch

from backend import council


class TitleGenerationTest(unittest.IsolatedAsyncioTestCase):
    async def test_initial_title_parses_json_and_cleans_punctuation(self):
        with (
            patch("backend.council.model_name", return_value="title-model"),
            patch("backend.council.model_list", return_value=[]),
            patch(
                "backend.council.query_model_with_fallbacks",
                new=AsyncMock(return_value={"content": "{\"title\":\"上下文管理优化。\"}"}),
            ) as title_call,
        ):
            title = await council.generate_initial_title("请优化对话历史管理")

        self.assertEqual(title, "上下文管理优化")
        prompt = title_call.await_args.args[1][0]["content"]
        self.assertIn("same primary language", prompt)
        self.assertIn("Return only valid JSON", prompt)

    async def test_context_title_retries_generic_title(self):
        with (
            patch("backend.council.model_name", return_value="title-model"),
            patch("backend.council.model_list", return_value=[]),
            patch(
                "backend.council.query_model_with_fallbacks",
                new=AsyncMock(side_effect=[
                    {"content": "{\"title\":\"New Conversation\"}"},
                    {"content": "```json\n{\"title\":\"Council Fallback Handling\"}\n```"},
                ]),
            ) as title_call,
        ):
            title = await council.generate_conversation_title_from_context("Conversation transcript: fallback behavior")

        self.assertEqual(title, "Council Fallback Handling")
        self.assertEqual(title_call.await_count, 2)
