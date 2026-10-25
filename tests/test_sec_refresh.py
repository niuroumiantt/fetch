"""Offline weekly refresh orchestration for fetchfilings."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetch.teams.fetchfilings.disclosures import build_disclosures, write_disclosures
from fetch.teams.fetchfilings.refresh import refresh
from fetch.teams.fetchfilings.sec import submissions_url

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class SecRefresh(unittest.TestCase):
    def test_build_disclosures_merges_sec_and_local_ir(self):
        microsoft = json.loads((FIXTURES / "sec_submissions_microsoft.json").read_text())
        listed = {
            "version": 1,
            "policy": {"scheduled_phase": "weekly"},
            "records": [
                {"company_id": "microsoft", "name": "Microsoft", "ticker": "NASDAQ:MSFT",
                 "cik": "0000789019", "channel": "sec_edgar"},
                {"company_id": "cambricon", "name": "Cambricon", "ticker": "SSE:688256",
                 "cik": None, "channel": "local_ir",
                 "ir_url": "https://www.cambricon.com/investor"},
                {"company_id": "hyosung", "name": "Hyosung", "ticker": "KRX:298040",
                 "cik": None, "channel": "local_ir", "ir_url": None},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "listed.json"
            seed.write_text(json.dumps(listed), encoding="utf-8")
            discoveries = {
                "version": 1,
                "finished_at": "2026-10-25T00:00:00+00:00",
                "records": [{
                    "company_id": "microsoft",
                    "status": "ok",
                    "filings": [{
                        "class": "annual",
                        "form": "10-K",
                        "report_date": "2026-06-30",
                        "filing_date": "2026-07-29",
                        "document_url": "https://www.sec.gov/Archives/edgar/data/789019/x/msft.htm",
                        "accession": "0001",
                    }],
                }],
            }
            (root / "discoveries").mkdir()
            (root / "discoveries" / "current.json").write_text(
                json.dumps(discoveries), encoding="utf-8")
            payload = build_disclosures(root, listed_path=seed)
            by_id = {r["company_id"]: r for r in payload["records"]}
            self.assertEqual(by_id["microsoft"]["financials"][0]["form"], "10-K")
            self.assertEqual(by_id["cambricon"]["financials"][0]["form"], "IR")
            self.assertEqual(by_id["hyosung"]["discovery_status"], "local_ir_no_url")
            written = write_disclosures(root, listed_path=seed)
            self.assertTrue(Path(written["path"]).is_file())

    def test_refresh_discover_only_with_mock(self):
        microsoft = json.loads((FIXTURES / "sec_submissions_microsoft.json").read_text())
        listed = {
            "version": 1,
            "policy": {"scheduled_phase": "weekly"},
            "records": [
                {"company_id": "microsoft", "name": "Microsoft", "ticker": "NASDAQ:MSFT",
                 "cik": "0000789019", "channel": "sec_edgar"},
            ],
        }

        class FakeFetcher:
            def get(self, url):
                assert url == submissions_url("0000789019")
                return {
                    "bytes": json.dumps(microsoft).encode(),
                    "content_type": "application/json",
                    "final_url": url,
                    "retrieved_at": "2026-10-25T00:00:00+00:00",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "listed.json"
            seed.write_text(json.dumps(listed), encoding="utf-8")
            with mock.patch("fetch.teams.fetchfilings.discover.Fetcher", return_value=FakeFetcher()):
                result = refresh(
                    data_root=root, listed_path=seed, collect_filings=False, respect_robots=False)
            self.assertEqual(result["discovery"]["counts"]["ok"], 1)
            self.assertEqual(result["collection"]["attempted"], 0)
            self.assertGreaterEqual(result["disclosures"]["counts"]["with_financials"], 1)


if __name__ == "__main__":
    unittest.main()
