import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import storage
from backend.main import app
from backend.provider_audit import canonical_digest, make_provider_request_audit


class ResumeStreamTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = storage.DATA_DIR
        storage.DATA_DIR = self.tmpdir.name
        self.client = TestClient(app)

    def tearDown(self):
        storage.DATA_DIR = self.original_data_dir
        self.tmpdir.cleanup()

    def _create_partial(self, updates=None):
        storage.create_conversation("conv-1")
        storage.add_user_message("conv-1", "hello")
        index = storage.create_assistant_partial("conv-1")
        if updates:
            storage.update_assistant_partial("conv-1", index, updates)
        return index

    def test_resume_from_stage1_when_no_stage_results_are_saved(self):
        index = self._create_partial({"status": "interrupted"})

        stage1 = [{"model": "a", "status": "success", "response": "answer"}]
        stage2 = [{"model": "b", "status": "success", "ranking": "FINAL RANKING:\n1. Response A"}]
        stage3 = {"model": "chair", "status": "success", "response": "final"}

        async def fake_stage1(user_query, conversation_history=None, event_callback=None, provider_audit_callback=None, audit_context=None):
            if provider_audit_callback:
                provider_audit_callback(make_provider_request_audit(
                    model="a",
                    messages=[{"role": "user", "content": user_query}],
                    stream=False,
                    call_kind="council_stage1",
                    stage="stage1",
                    provider_function="stage1_collect_responses_streaming",
                    source_map=(audit_context or {}).get("source_map"),
                    turn_lineage=(audit_context or {}).get("turn_lineage"),
                ))
            return stage1

        async def fake_stage2(user_query, stage1_results, conversation_history=None, event_callback=None, provider_audit_callback=None, audit_context=None):
            if provider_audit_callback:
                provider_audit_callback(make_provider_request_audit(
                    model="b",
                    messages=[{"role": "user", "content": user_query}],
                    stream=False,
                    call_kind="council_stage2",
                    stage="stage2",
                    provider_function="stage2_collect_rankings_streaming",
                    source_map=(audit_context or {}).get("source_map"),
                    turn_lineage=(audit_context or {}).get("turn_lineage"),
                ))
            return stage2, {"Response A": "a"}

        async def fake_stage3(user_query, stage1_results, stage2_results, conversation_history=None, event_callback=None, provider_audit_callback=None, audit_context=None):
            if provider_audit_callback:
                provider_audit_callback(make_provider_request_audit(
                    model="chair",
                    messages=[{"role": "user", "content": user_query}],
                    stream=False,
                    call_kind="council_stage3",
                    stage="stage3",
                    provider_function="stage3_synthesize_final_with_history",
                    source_map=(audit_context or {}).get("source_map"),
                    turn_lineage=(audit_context or {}).get("turn_lineage"),
                ))
            return stage3

        with (
            patch("backend.main.stage1_collect_responses_streaming", new=AsyncMock(side_effect=fake_stage1)) as stage1_mock,
            patch("backend.main.stage2_collect_rankings_streaming", new=AsyncMock(side_effect=fake_stage2)) as stage2_mock,
            patch("backend.main.stage3_synthesize_final_with_history", new=AsyncMock(side_effect=fake_stage3)) as stage3_mock,
        ):
            response = self.client.post(f"/api/conversations/conv-1/messages/{index}/resume/stream")

        self.assertEqual(response.status_code, 200)
        stage1_mock.assert_awaited_once()
        stage2_mock.assert_awaited_once()
        stage3_mock.assert_awaited_once()

        conversation = storage.get_conversation("conv-1")
        assistant = conversation["messages"][index]
        self.assertEqual(assistant["status"], "complete")
        self.assertEqual(assistant["stage1"], stage1)
        self.assertEqual(assistant["stage2"], stage2)
        self.assertEqual(assistant["stage3"], stage3)
        provider_audit = conversation["turns"][0]["context_payload"]["provider_request_audit"]
        self.assertEqual([entry["stage"] for entry in provider_audit], ["stage1", "stage2", "stage3"])
        for entry in provider_audit:
            self.assertEqual(entry["turn_lineage"]["user_message_index"], 0)
            self.assertEqual(entry["turn_lineage"]["turn_id"], conversation["turns"][0]["id"])
            self.assertEqual(entry["source_map"]["current_message_ref"]["message_index"], 0)
            self.assertEqual(canonical_digest(entry["payload_preview"]), entry["digest"])

    def test_resume_from_stage2_when_stage1_is_saved(self):
        stage1 = [{"model": "a", "status": "success", "response": "answer"}]
        index = self._create_partial({
            "status": "interrupted",
            "stage1": stage1,
        })

        stage2 = [{"model": "b", "status": "success", "ranking": "FINAL RANKING:\n1. Response A"}]
        stage3 = {"model": "chair", "status": "success", "response": "final"}

        with (
            patch("backend.main.stage1_collect_responses_streaming", new=AsyncMock()) as stage1_mock,
            patch("backend.main.stage2_collect_rankings_streaming", new=AsyncMock(return_value=(stage2, {"Response A": "a"}))) as stage2_mock,
            patch("backend.main.stage3_synthesize_final_with_history", new=AsyncMock(return_value=stage3)) as stage3_mock,
        ):
            response = self.client.post(f"/api/conversations/conv-1/messages/{index}/resume/stream")

        self.assertEqual(response.status_code, 200)
        stage1_mock.assert_not_awaited()
        stage2_mock.assert_awaited_once()
        stage3_mock.assert_awaited_once()

        assistant = storage.get_conversation("conv-1")["messages"][index]
        self.assertEqual(assistant["stage1"], stage1)
        self.assertEqual(assistant["stage2"], stage2)
        self.assertEqual(assistant["stage3"], stage3)

    def test_resume_from_stage3_when_stage1_and_stage2_are_saved(self):
        stage1 = [{"model": "a", "status": "success", "response": "answer"}]
        stage2 = [{"model": "b", "status": "success", "ranking": "FINAL RANKING:\n1. Response A"}]
        metadata = {"label_to_model": {"Response A": "a"}, "aggregate_rankings": []}
        index = self._create_partial({
            "status": "interrupted",
            "stage1": stage1,
            "stage2": stage2,
            "metadata": metadata,
        })

        stage3 = {"model": "chair", "status": "success", "response": "final"}

        with (
            patch("backend.main.stage1_collect_responses_streaming", new=AsyncMock()) as stage1_mock,
            patch("backend.main.stage2_collect_rankings_streaming", new=AsyncMock()) as stage2_mock,
            patch("backend.main.stage3_synthesize_final_with_history", new=AsyncMock(return_value=stage3)) as stage3_mock,
        ):
            response = self.client.post(f"/api/conversations/conv-1/messages/{index}/resume/stream")

        self.assertEqual(response.status_code, 200)
        stage1_mock.assert_not_awaited()
        stage2_mock.assert_not_awaited()
        stage3_mock.assert_awaited_once()

        assistant = storage.get_conversation("conv-1")["messages"][index]
        self.assertEqual(assistant["status"], "complete")
        self.assertEqual(assistant["stage1"], stage1)
        self.assertEqual(assistant["stage2"], stage2)
        self.assertEqual(assistant["metadata"]["label_to_model"], metadata["label_to_model"])
        self.assertEqual(assistant["metadata"]["aggregate_rankings"], metadata["aggregate_rankings"])
        self.assertEqual(assistant["metadata"]["mode"], "council_resume")
        self.assertEqual(assistant["metadata"]["context_snapshot"]["mode"], "council_resume")
        self.assertEqual(assistant["stage3"], stage3)

    def test_resume_reruns_stage2_when_saved_stage2_has_no_successful_rankings(self):
        stage1 = [{"model": "a", "status": "success", "response": "answer"}]
        failed_stage2 = [{"model": "b", "status": "failed", "error": "timeout"}]
        index = self._create_partial({
            "status": "interrupted",
            "stage1": stage1,
            "stage2": failed_stage2,
            "metadata": {"label_to_model": {"Response A": "a"}, "aggregate_rankings": []},
        })

        recovered_stage2 = [{"model": "b", "status": "success", "ranking": "FINAL RANKING:\n1. Response A"}]
        stage3 = {"model": "chair", "status": "success", "response": "final"}

        with (
            patch("backend.main.stage1_collect_responses_streaming", new=AsyncMock()) as stage1_mock,
            patch("backend.main.stage2_collect_rankings_streaming", new=AsyncMock(return_value=(recovered_stage2, {"Response A": "a"}))) as stage2_mock,
            patch("backend.main.stage3_synthesize_final_with_history", new=AsyncMock(return_value=stage3)) as stage3_mock,
        ):
            response = self.client.post(f"/api/conversations/conv-1/messages/{index}/resume/stream")

        self.assertEqual(response.status_code, 200)
        stage1_mock.assert_not_awaited()
        stage2_mock.assert_awaited_once()
        stage3_mock.assert_awaited_once()

        assistant = storage.get_conversation("conv-1")["messages"][index]
        self.assertEqual(assistant["stage2"], recovered_stage2)
        self.assertEqual(assistant["stage3"], stage3)

    def test_resume_rebuilds_stage2_metadata_when_saved_stage2_is_usable(self):
        stage1 = [{"model": "a", "status": "success", "response": "answer"}]
        stage2 = [{
            "model": "b",
            "status": "success",
            "ranking": "FINAL RANKING:\n1. Response A",
            "parsed_ranking": ["Response A"],
        }]
        index = self._create_partial({
            "status": "interrupted",
            "stage1": stage1,
            "stage2": stage2,
            "metadata": {},
        })

        stage3 = {"model": "chair", "status": "success", "response": "final"}

        with (
            patch("backend.main.stage1_collect_responses_streaming", new=AsyncMock()) as stage1_mock,
            patch("backend.main.stage2_collect_rankings_streaming", new=AsyncMock()) as stage2_mock,
            patch("backend.main.stage3_synthesize_final_with_history", new=AsyncMock(return_value=stage3)) as stage3_mock,
        ):
            response = self.client.post(f"/api/conversations/conv-1/messages/{index}/resume/stream")

        self.assertEqual(response.status_code, 200)
        stage1_mock.assert_not_awaited()
        stage2_mock.assert_not_awaited()
        stage3_mock.assert_awaited_once()

        assistant = storage.get_conversation("conv-1")["messages"][index]
        self.assertEqual(assistant["metadata"]["label_to_model"], {"Response A": "a"})
        self.assertEqual(assistant["metadata"]["aggregate_rankings"][0]["model"], "a")
        self.assertEqual(assistant["stage3"], stage3)


if __name__ == "__main__":
    unittest.main()
