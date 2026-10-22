import io
import unittest
from urllib.error import HTTPError

from fetch.core.failures import FlowError
from fetch.core.http import Fetcher, check_url, decode_body


class Http(unittest.TestCase):
    def test_check_url_rejects_http_and_credentials(self):
        with self.assertRaises(FlowError):
            check_url("http://example.com/", {"example.com"})
        with self.assertRaises(FlowError):
            check_url("https://user:pass@example.com/", {"example.com"})

    def test_decode_gzip(self):
        import gzip
        body = gzip.compress(b"hello")
        self.assertEqual(decode_body("gzip", body, 100), b"hello")
        with self.assertRaises(FlowError):
            decode_body("gzip", b"not-gzip", 100)

    def test_fetcher_get_with_fake_opener(self):
        class Response:
            def __init__(self):
                self.url = "https://example.com/a"
                self.status = 200
                self.headers = _Headers()

            def read(self, n):
                return b"<!DOCTYPE html><html></html>"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Headers(dict):
            def get_content_type(self):
                return "text/html"

            def get(self, key, default=None):
                return dict.get(self, key, default)

        class Opener:
            def open(self, request, timeout=None):
                return Response()

        sleeps = []
        fetcher = Fetcher({"example.com"}, respect_robots=False, opener=Opener(),
                          sleep=sleeps.append, delay_seconds=0)
        result = fetcher.get("https://example.com/a")
        self.assertEqual(result["status"], 200)
        self.assertEqual(len(result["sha256"]), 64)

    def test_robots_fail_closed(self):
        class Opener:
            def open(self, request, timeout=None):
                raise HTTPError(request.full_url, 500, "err", hdrs={}, fp=io.BytesIO())

        fetcher = Fetcher({"example.com"}, respect_robots=True, opener=Opener(),
                          sleep=lambda _: None, delay_seconds=0)
        with self.assertRaises(FlowError) as ctx:
            fetcher.get("https://example.com/page")
        self.assertEqual(ctx.exception.code, "robots_unavailable")


if __name__ == "__main__":
    unittest.main()
