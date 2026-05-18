import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class StageModelStatusEventsTest(unittest.TestCase):
    def test_stage1_stream_helper_emits_per_model_events(self):
        async def fake_query(model, messages, event_callback=None):
            if event_callback:
                await event_callback({"status": "running"})
            if model == "bad-model":
                return {"status": "failed", "model": model, "error_type": "timeout", "error": "slow"}
            return {"status": "success", "model": model, "content": f"{model} answer", "usage": {}}

        async def run_helper():
            from backend.council import stage1_collect_responses_streaming

            events = []
            results = await stage1_collect_responses_streaming(
                "hello",
                None,
                ["good-model", "bad-model"],
                lambda event: events.append(event),
            )
            return events, results

        with patch("backend.council.query_model", new=AsyncMock(side_effect=fake_query)):
            events, results = asyncio.run(run_helper())

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types.count("stage1_model_start"), 2)
        self.assertIn("stage1_model_running", event_types)
        self.assertIn("stage1_model_complete", event_types)
        self.assertIn("stage1_model_failed", event_types)
        self.assertEqual([result["model"] for result in results], ["good-model", "bad-model"])
        self.assertEqual(results[1]["status"], "failed")

    def test_stage3_synthesis_emits_chairman_model_events(self):
        async def fake_query(model, messages, event_callback=None):
            if event_callback:
                await event_callback({"status": "first_event", "first_event_seconds": 0.2})
            return {
                "status": "success",
                "model": model,
                "content": "final answer",
                "usage": {},
                "duration_seconds": 1.3,
                "first_event_seconds": 0.2,
                "streamed": True,
            }

        async def run_helper():
            from backend.council import stage3_synthesize_final_with_history

            events = []
            result = await stage3_synthesize_final_with_history(
                "hello",
                [{"model": "a", "status": "success", "response": "answer"}],
                [{"model": "b", "status": "success", "ranking": "FINAL RANKING:\n1. Response A"}],
                event_callback=lambda event: events.append(event),
            )
            return events, result

        with (
            patch("backend.council.model_name", return_value="chairman-model"),
            patch("backend.council.query_model", new=AsyncMock(side_effect=fake_query)),
        ):
            events, result = asyncio.run(run_helper())

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types[0], "stage3_model_start")
        self.assertIn("stage3_model_first_event", event_types)
        self.assertEqual(event_types[-1], "stage3_model_complete")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["response"], "final answer")
        self.assertTrue(result["streamed"])


if __name__ == "__main__":
    unittest.main()
