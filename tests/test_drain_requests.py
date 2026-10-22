"""Offline tests for website queue drain. No outbound crawl of source hosts."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetch.drain import drain, _report_payload
from fetch.core.failures import FlowError


class DrainRequests(unittest.TestCase):
    def test_report_payload_never_includes_exception_text(self):
        payload = _report_payload(error=FlowError("registered_field_not_found", "source_schema"))
        self.assertEqual(payload["outcome"], "failed")
        self.assertEqual(payload["failure_code"], "registered_field_not_found")
        self.assertNotIn("Exception", json.dumps(payload))
        self.assertNotIn("Traceback", json.dumps(payload))

    def test_drain_claims_runs_and_reports_without_network_collect(self):
        calls = []

        def fake_request(base, token, method, path, body=None, timeout=60):
            calls.append((method, path, body))
            if path.endswith("/pending"):
                return 200, {"ok": True, "requests": [{
                    "id": "req-1", "provider_id": "fetchstat",
                    "source_id": "fetchstat-eia-bootstrap", "status": "requested"}]}
            if path.endswith("/claim"):
                return 200, {"ok": True, "request": {"id": "req-1"}, "replayed": False}
            if path.endswith("/report"):
                return 200, {"ok": True, "receive": None}
            return 404, {"ok": False}

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FETCH_DRAIN_ALLOW_HTTP"] = "1"
            try:
                with mock.patch("fetch.drain._request", side_effect=fake_request), \
                        mock.patch("fetch.collect.collect", return_value={
                            "delivery_id": "fetchstat-deadbeef-v1",
                            "package": str(Path(tmp) / "pkg"),
                            "acquisition_sha256": "a" * 64,
                            "candidate_rows": 1,
                            "unique_originals": 1,
                            "offline_valid": True,
                            "acquisition_retrieved_at": None,
                            "replayed": True,
                        }):
                    summary = drain(
                        "http://127.0.0.1:9", "t" * 32,
                        collector_host="test-host", limit=5, respect_robots=False)
            finally:
                os.environ.pop("FETCH_DRAIN_ALLOW_HTTP", None)
        self.assertEqual(summary["claimed"], 1)
        self.assertEqual(summary["reported"], 1)
        self.assertEqual(summary["results"][0]["outcome"], "success")
        self.assertEqual(summary["results"][0]["delivery_id"], "fetchstat-deadbeef-v1")
        self.assertTrue(any(c[0] == "POST" and c[1].endswith("/claim") for c in calls))
        self.assertTrue(any(c[0] == "POST" and c[1].endswith("/report") for c in calls))

    def test_cli_help_lists_drain_requests(self):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["python3", "fetch", "drain-requests", "-h"],
            cwd=root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--api-base", result.stdout)


if __name__ == "__main__":
    unittest.main()
