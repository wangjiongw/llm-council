import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend import storage


class VersionAPITest(unittest.TestCase):
    def test_version_endpoint_returns_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_data_dir = storage.DATA_DIR
            storage.DATA_DIR = tmpdir
            try:
                with patch.dict(os.environ, {"LLM_COUNCIL_COMMIT": "testcommit", "BACKEND_HOST": "127.0.0.1", "BACKEND_PORT": "18001"}):
                    response = TestClient(app).get("/api/version")
            finally:
                storage.DATA_DIR = original_data_dir

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["commit"], "testcommit")
        self.assertEqual(payload["backend_host"], "127.0.0.1")
        self.assertEqual(payload["backend_port"], "18001")
        self.assertEqual(payload["data_dir"], tmpdir)
        self.assertIsInstance(payload["pid"], int)
        self.assertTrue(payload["started_at"])
        self.assertRegex(payload["python"], r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
