import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.council import run_full_council_with_history
from backend.openrouter import query_model
from backend.provider_audit import canonical_digest, make_provider_request_audit


class ProviderRequestAuditTest(unittest.TestCase):
    def test_query_model_emits_audit_safe_provider_payload_before_request(self):
        entries = []
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,RAW_IMAGE_BYTES"},
                    "attachment_ref": {"id": "att-1", "type": "image/png"},
                },
            ],
        }]

        async def run():
            with (
                patch("backend.openrouter.resolve_model_config", return_value={
                    "enabled": True,
                    "timeout": 30,
                    "stream": False,
                    "chat_url": "https://example.invalid/chat",
                    "api_key": "secret",
                }),
                patch("backend.openrouter._query_model_non_streaming", new=AsyncMock(return_value={
                    "status": "success",
                    "model": "audit-model",
                    "content": "ok",
                })),
            ):
                return await query_model(
                    "audit-model",
                    messages,
                    provider_audit_callback=entries.append,
                    audit_context={
                        "source_map": {"message_refs": [{"message_index": 3}]},
                        "turn_lineage": {"conversation_id": "conv-1", "mode": "quick"},
                    },
                    call_kind="quick",
                    stage="quick",
                )

        response = asyncio.run(run())

        self.assertEqual(response["content"], "ok")
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["call_kind"], "quick")
        self.assertEqual(entry["stage"], "quick")
        self.assertEqual(entry["model"], "audit-model")
        self.assertEqual(entry["provider_function"], "query_model")
        self.assertEqual(entry["source_map"]["message_refs"][0]["provider_message_index"], 0)
        self.assertEqual(entry["source_map"]["context_package_message_refs"][0]["message_index"], 3)
        persisted = str(entry)
        self.assertNotIn("RAW_IMAGE_BYTES", persisted)
        self.assertNotIn("secret", persisted)
        self.assertIn("[redacted image data URI]", persisted)
        self.assertEqual(canonical_digest(entry["payload_preview"]), entry["digest"])

    def test_provider_digest_is_stable_after_redaction(self):
        messages = [{
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}],
        }]
        first = make_provider_request_audit(
            model="m",
            messages=messages,
            stream=True,
            call_kind="quick",
            stage="quick",
            provider_function="test",
        )
        second = make_provider_request_audit(
            model="m",
            messages=messages,
            stream=True,
            call_kind="quick",
            stage="quick",
            provider_function="test",
        )

        self.assertEqual(first["digest"], second["digest"])

    def test_council_stage_provider_audit_captures_all_stages(self):
        entries = []

        async def fake_query_model(
            model,
            messages,
            timeout=None,
            event_callback=None,
            provider_audit_callback=None,
            audit_context=None,
            call_kind="model",
            stage="model",
            provider_function="query_model",
            attempt=None,
        ):
            if provider_audit_callback:
                provider_audit_callback(make_provider_request_audit(
                    model=model,
                    messages=messages,
                    stream=False,
                    call_kind=call_kind,
                    stage=stage,
                    provider_function=provider_function,
                    source_map=(audit_context or {}).get("source_map"),
                    turn_lineage=(audit_context or {}).get("turn_lineage"),
                    attempt=attempt,
                    metadata=(audit_context or {}).get("metadata"),
                ))
            if stage == "stage2":
                content = "**FINAL RANKING:**\n1. Response A\n2. Response B"
            elif stage == "stage3":
                content = "final synthesis"
            else:
                content = f"{stage} answer from {model}"
            return {
                "status": "success",
                "model": model,
                "content": content,
                "response": content,
                "id": f"resp-{model}-{stage}",
                "usage": {},
                "finish_reason": "stop",
            }

        async def run():
            with (
                patch("backend.council.model_list", side_effect=lambda key: {
                    "council_models": ["council-a", "council-b"],
                    "chairman_fallback_models": [],
                }.get(key, [])),
                patch("backend.council.model_name", side_effect=lambda key: {
                    "chairman_model": "chairman",
                    "quick_model": "quick",
                }.get(key, key)),
                patch("backend.openrouter.query_model", new=fake_query_model),
                patch("backend.council.query_model", new=fake_query_model),
            ):
                return await run_full_council_with_history(
                    "current question",
                    [{"role": "user", "content": "previous question"}],
                    provider_audit_callback=entries.append,
                    audit_context={
                        "source_map": {"message_refs": [{"message_index": 0, "source": "history"}]},
                        "turn_lineage": {
                            "conversation_id": "conv-1",
                            "mode": "council",
                            "user_message_index": 2,
                            "turn_id": "turn-1",
                        },
                    },
                )

        stage1_results, stage2_results, stage3_result, _metadata = asyncio.run(run())

        self.assertTrue(stage1_results)
        self.assertTrue(stage2_results)
        self.assertEqual(stage3_result["response"], "final synthesis")
        stages = [entry["stage"] for entry in entries]
        self.assertEqual(stages.count("stage1"), 2)
        self.assertEqual(stages.count("stage2"), 2)
        self.assertEqual(stages.count("stage3"), 1)
        for entry in entries:
            self.assertEqual(canonical_digest(entry["payload_preview"]), entry["digest"])
            self.assertEqual(entry["turn_lineage"]["user_message_index"], 2)
            self.assertEqual(entry["turn_lineage"]["turn_id"], "turn-1")
            self.assertEqual(entry["source_map"]["current_message_ref"]["message_index"], 2)
            self.assertEqual(entry["source_map"]["context_package_message_refs"][0]["message_index"], 0)


if __name__ == "__main__":
    unittest.main()
