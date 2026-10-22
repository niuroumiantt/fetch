import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetch.contract.envelope import validate
from fetch.contract.package import build
from fetch.core.store import Store


HTML = b"<!DOCTYPE html><html><body><p>ok</p></body></html>"


class StoreAndPackage(unittest.TestCase):
    def test_put_once_and_package_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            path, meta, created = store.put(HTML, "html", retrieved_at="2026-10-22T00:00:00+00:00")
            self.assertTrue(created)
            again = store.put(HTML, "html", retrieved_at="2026-10-22T01:00:00+00:00")
            self.assertFalse(again[2])
            self.assertEqual(again[1]["retrieved_at"], meta["retrieved_at"])
            sha = meta["sha256"]
            item = {
                "item_id": "src:" + sha[:24],
                "source_id": "src",
                "source_item_id": "native-1",
                "url": "https://example.com/page",
                "content_type": "text/html",
                "format": "html",
                "sha256": sha,
                "bytes": len(HTML),
                "retrieved_at": meta["retrieved_at"],
                "publisher": "Example",
                "title": "page",
            }
            with mock.patch("fetch.contract.package.collector_revision",
                            return_value="a" * 40):
                first = build("fetchstat", [item], temp, revision="a" * 40)
                second = build("fetchstat", [item], temp, revision="a" * 40)
            self.assertFalse(first["replayed"])
            self.assertTrue(second["replayed"])
            self.assertTrue(first["offline_valid"])
            report = validate(first["package"])
            self.assertTrue(report["offline_valid"])
            self.assertEqual(report["provider_id"], "fetchstat")
            manifest = json.loads(Path(first["package"], "manifest.json").read_text())
            self.assertEqual(manifest["contract_version"], "2.0")
            self.assertTrue(manifest["items"][0]["path"].startswith("files/"))


if __name__ == "__main__":
    unittest.main()
