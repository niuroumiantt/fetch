import json
import tempfile
import unittest
from pathlib import Path

from fetch.core.formats import matches


class Formats(unittest.TestCase):
    def test_pdf_and_html(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "a.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%")
            html = root / "a.html"
            html.write_bytes(b"<!DOCTYPE html><html></html>")
            self.assertTrue(matches(pdf, "pdf"))
            self.assertTrue(matches(html, "html"))
            self.assertFalse(matches(html, "pdf"))

    def test_json_object_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ok = root / "a.json"
            ok.write_text(json.dumps({"k": 1}), encoding="utf-8")
            bad = root / "b.json"
            bad.write_text("[1,2]", encoding="utf-8")
            self.assertTrue(matches(ok, "json"))
            self.assertFalse(matches(bad, "json"))


if __name__ == "__main__":
    unittest.main()
