import asyncio
import tempfile
import httpx
import unittest
from unittest.mock import patch

from backend import llm_settings


class FakeStreamResponse:
    status_code = 200
    text = ""
    is_error = False

    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeStreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAsyncClient:
    last_payload = None
    last_timeout = None

    def __init__(self, timeout):
        FakeAsyncClient.last_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers=None, json=None):
        FakeAsyncClient.last_payload = json
        return FakeStreamContext(FakeStreamResponse([
            'data: {"id":"stream-id","model":"stream-model","choices":[{"delta":{"content":"hello"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}],"usage":{"total_tokens":3}}',
            'data: [DONE]',
        ]))


class FakeStreamingHTTPErrorClient:
    last_payload = None

    def __init__(self, timeout):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers=None, json=None):
        FakeStreamingHTTPErrorClient.last_payload = json
        request = httpx.Request(method, url)
        response = httpx.Response(429, request=request, stream=httpx.ByteStream(b'{"error":"rate limit"}'))
        return FakeStreamContext(response)


class StreamingModelQueryTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_settings_path = llm_settings.SETTINGS_PATH
        llm_settings.SETTINGS_PATH = llm_settings.Path(self.tmpdir.name) / "llm_settings.json"

    def tearDown(self):
        llm_settings.SETTINGS_PATH = self.original_settings_path
        self.tmpdir.cleanup()

    def test_query_model_stream_collects_chunks_after_first_event(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {
                "base_url": "https://default.example/v1",
                "api_key": "default-key",
                "timeout": 180,
                "stream": True,
            },
        })

        async def run_query():
            from backend.openrouter import query_model

            return await query_model("stream-model", [{"role": "user", "content": "hello"}])

        with patch("backend.openrouter.httpx.AsyncClient", FakeAsyncClient):
            result = asyncio.run(run_query())

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["content"], "hello world")
        self.assertEqual(result["response"], "hello world")
        self.assertEqual(result["response_id"], "stream-id")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["usage"], {"total_tokens": 3})
        self.assertTrue(result["streamed"])
        self.assertTrue(result["first_event_seconds"] >= 0)
        self.assertTrue(FakeAsyncClient.last_payload["stream"])
        self.assertIsNone(FakeAsyncClient.last_timeout.read)

    def test_query_model_streaming_http_error_reads_error_body(self):
        llm_settings.save_llm_settings({
            **llm_settings.DEFAULT_SETTINGS,
            "default_provider": {
                "base_url": "https://default.example/v1",
                "api_key": "default-key",
                "timeout": 180,
                "stream": True,
            },
        })

        async def run_query():
            from backend.openrouter import query_model

            return await query_model("stream-model", [{"role": "user", "content": "hello"}])

        with patch("backend.openrouter.httpx.AsyncClient", FakeStreamingHTTPErrorClient):
            result = asyncio.run(run_query())

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_type"], "http_status")
        self.assertEqual(result["status_code"], 429)
        self.assertIn("rate limit", result["error"])
        self.assertNotIn("Attempted to access streaming response content", result["error"])
        self.assertTrue(FakeStreamingHTTPErrorClient.last_payload["stream"])


if __name__ == "__main__":
    unittest.main()
