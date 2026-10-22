import unittest
from urllib.error import HTTPError

from fetch.core.failures import FlowError, classify, retry_after


class Failures(unittest.TestCase):
    def test_flow_error_category(self):
        error = FlowError("busy_now", "busy")
        result = classify(error, "acquisition")
        self.assertTrue(result["retryable"])
        self.assertEqual(result["code"], "busy_now")

    def test_transient_http(self):
        error = HTTPError("https://example.com", 503, "unavailable", hdrs={"Retry-After": "2"}, fp=None)
        result = classify(error, "acquisition")
        self.assertTrue(result["retryable"])
        self.assertEqual(result["retry_after_seconds"], 2)

    def test_retry_after_rejects_naive_date(self):
        self.assertIsNone(retry_after({"Retry-After": "Wed, 21 Oct 2015 07:28:00"}))


if __name__ == "__main__":
    unittest.main()
