import asyncio
import tempfile
import unittest

from fastapi.testclient import TestClient

from backend import storage
from backend.council import build_quick_messages
from backend.main import _context_messages, _context_payload, app
from backend.provider_audit import make_provider_request_audit


class ContextPayloadV2Test(unittest.TestCase):
    def test_context_payload_v2_redacts_images_and_keeps_legacy_fields(self):
        context_package = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "see image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,RAW_IMAGE_BYTES"},
                        "attachment_ref": {"id": "att-1", "type": "image/png"},
                    },
                ],
            }],
            "source_messages": [{"role": "user", "content": "source text", "source": "history", "message_index": 4}],
            "current_content": "current",
            "snapshot": {"mode": "quick", "estimated_context_tokens": 8},
        }
        provider_audit = [make_provider_request_audit(
            model="m",
            messages=context_package["messages"],
            stream=True,
            call_kind="quick",
            stage="quick",
            provider_function="test",
        )]

        payload = _context_payload(context_package, provider_audit)
        persisted = str(payload)

        self.assertEqual(payload["schema"], "context_payload_v2")
        self.assertIn("context_package_audit", payload)
        self.assertEqual(payload["provider_request_audit"], provider_audit)
        self.assertEqual(payload["model_messages"], payload["context_package_audit"]["model_messages"])
        self.assertEqual(payload["audit_messages"], payload["context_package_audit"]["audit_messages"])
        self.assertNotIn("RAW_IMAGE_BYTES", persisted)
        self.assertIn("[redacted image data URI]", persisted)
        self.assertFalse(payload["context_package_audit"]["exact_provider_request"])

    def test_replay_compares_saved_quick_provider_digest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_data_dir = storage.DATA_DIR
            storage.DATA_DIR = tmpdir
            try:
                client = TestClient(app)
                storage.create_conversation("conv-1")
                first_user_index = storage.add_user_message("conv-1", "first question")
                first_assistant_index = storage.add_assistant_message(
                    "conv-1",
                    [],
                    [],
                    {"model": "m", "status": "success", "response": "first answer"},
                    metadata={"mode": "quick"},
                )
                storage.create_turn_record(
                    "conv-1",
                    user_message_index=first_user_index,
                    assistant_message_index=first_assistant_index,
                    mode="quick",
                    status="complete",
                )
                second_user_index = storage.add_user_message("conv-1", "second question")
                second_assistant_index = storage.add_assistant_message(
                    "conv-1",
                    [],
                    [],
                    {"model": "m", "status": "success", "response": "second answer"},
                    metadata={"mode": "quick"},
                )
                turn = storage.create_turn_record(
                    "conv-1",
                    user_message_index=second_user_index,
                    assistant_message_index=second_assistant_index,
                    mode="quick",
                    status="complete",
                )
                context_package = asyncio.run(storage.build_context_package(
                    "conv-1",
                    before_index=second_user_index,
                    current_content="second question",
                    mode="quick",
                ))
                provider_messages = build_quick_messages("second question", _context_messages(context_package))
                provider_audit = [make_provider_request_audit(
                    model="m",
                    messages=provider_messages,
                    stream=False,
                    call_kind="quick",
                    stage="quick",
                    provider_function="quick_query",
                )]
                storage.update_turn_record(
                    "conv-1",
                    turn["id"],
                    context_snapshot=context_package["snapshot"],
                    context_payload=_context_payload(context_package, provider_audit),
                )

                response = client.post(
                    f"/api/conversations/conv-1/messages/{second_user_index}/context/replay",
                    json={},
                )
            finally:
                storage.DATA_DIR = original_data_dir

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["replay_kind"], "saved_provider_request_audit")
        self.assertTrue(payload["provider_digest_comparison"]["same_provider_request"])
        self.assertEqual(
            payload["saved_provider_request_audit"][0]["digest"],
            payload["rebuilt_provider_request_audit"][0]["digest"],
        )


if __name__ == "__main__":
    unittest.main()
