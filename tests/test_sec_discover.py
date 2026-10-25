"""Offline SEC submissions discovery and sec_filing adapter."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetch.collect import collect
from fetch.contract.envelope import validate
from fetch.teams.fetchfilings.discover import discover, discovered_sources
from fetch.teams.fetchfilings.listed import sec_edgar_companies
from fetch.teams.fetchfilings.sec import pick_latest_periodic, source_for_filing, submissions_url

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class SecDiscover(unittest.TestCase):
    def test_listed_seed_has_forty_sec_edgar(self):
        rows = sec_edgar_companies()
        self.assertEqual(len(rows), 40)
        self.assertTrue(all(r.get("cik") for r in rows))

    def test_pick_microsoft_10k_and_10q(self):
        payload = json.loads((FIXTURES / "sec_submissions_microsoft.json").read_text())
        filings = pick_latest_periodic(payload, cik="0000789019")
        forms = [f["form"] for f in filings]
        self.assertEqual(forms, ["10-K", "10-Q"])
        self.assertTrue(filings[0]["document_url"].startswith(
            "https://www.sec.gov/Archives/edgar/data/789019/"))
        self.assertIn("index_url", filings[0])

    def test_pick_alibaba_20f_only(self):
        payload = json.loads((FIXTURES / "sec_submissions_alibaba.json").read_text())
        filings = pick_latest_periodic(payload, cik="0001577552")
        self.assertEqual([f["form"] for f in filings], ["20-F"])
        self.assertEqual(filings[0]["class"], "annual")

    def test_source_for_filing_shape(self):
        company = {
            "company_id": "microsoft",
            "name": "Microsoft",
            "ticker": "NASDAQ:MSFT",
            "cik": "0000789019",
        }
        payload = json.loads((FIXTURES / "sec_submissions_microsoft.json").read_text())
        filing = pick_latest_periodic(payload, cik=company["cik"])[0]
        source = source_for_filing(company, filing)
        self.assertEqual(source["adapter"], "sec_filing")
        self.assertEqual(source["hosts"], ["www.sec.gov"])
        self.assertEqual(source["filing"]["form"], "10-K")
        self.assertTrue(source["id"].startswith("fetchfilings-sec-microsoft-"))

    def test_discover_writes_ledger_with_mock_fetcher(self):
        microsoft = json.loads((FIXTURES / "sec_submissions_microsoft.json").read_text())
        alibaba = json.loads((FIXTURES / "sec_submissions_alibaba.json").read_text())
        bodies = {
            submissions_url("0000789019"): json.dumps(microsoft).encode(),
            submissions_url("0001577552"): json.dumps(alibaba).encode(),
        }

        class FakeFetcher:
            def get(self, url):
                return {
                    "bytes": bodies[url],
                    "content_type": "application/json",
                    "final_url": url,
                    "retrieved_at": "2026-10-25T00:00:00+00:00",
                }

        listed = {
            "version": 1,
            "records": [
                {"company_id": "microsoft", "name": "Microsoft", "ticker": "NASDAQ:MSFT",
                 "cik": "0000789019", "channel": "sec_edgar"},
                {"company_id": "alibaba", "name": "Alibaba", "ticker": "NYSE:BABA",
                 "cik": "0001577552", "channel": "sec_edgar"},
                {"company_id": "kddi", "name": "KDDI", "ticker": "TYO:9433",
                 "cik": None, "channel": "local_ir"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "listed.json"
            seed.write_text(json.dumps(listed), encoding="utf-8")
            root = Path(tmp) / "data"
            result = discover(data_root=root, listed_path=seed, fetcher=FakeFetcher(),
                              respect_robots=False)
            self.assertEqual(result["counts"]["ok"], 2)
            self.assertEqual(result["counts"]["filings"], 3)
            sources = discovered_sources(root)
            self.assertEqual(len(sources), 3)
            self.assertEqual(len(discovered_sources(root, company_id="microsoft")), 2)

    def test_sec_filing_adapter_packages(self):
        company = {
            "company_id": "microsoft",
            "name": "Microsoft Corporation",
            "ticker": "NASDAQ:MSFT",
            "cik": "0000789019",
        }
        payload = json.loads((FIXTURES / "sec_submissions_microsoft.json").read_text())
        filing = pick_latest_periodic(payload, cik=company["cik"])[0]
        source = source_for_filing(company, filing)
        html = b"<html><body>Form 10-K MICROSOFT CORP synthetic</body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp) / "filing.htm"
            native.write_bytes(html)
            with mock.patch("fetch.collect.collector_revision", return_value="a" * 40):
                result = collect(source, Path(tmp) / "data", local=native,
                                 provenance="SYNTHETIC test only", revision="a" * 40,
                                 respect_robots=False)
            package = Path(result["package"])
            self.assertTrue(validate(package)["offline_valid"])
            rows = [json.loads(line) for line in
                    (package / "observations.jsonl").read_text().splitlines() if line]
            self.assertEqual(rows[0]["metric"], "disclosure.sec.periodic_form")
            self.assertEqual(rows[0]["value"]["text"], "10-K")
            self.assertEqual(rows[0]["links"]["document_url"], filing["document_url"])


if __name__ == "__main__":
    unittest.main()
