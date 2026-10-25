"""Offline tests for listed-universe multi-lane refresh."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetch.listed.quotes import normalize, us_listed
from fetch.listed.refresh import SPEC_OVERLAP, specs_status
from fetch.teams.fetchfilings.adapters.ir_page import Adapter as IrAdapter

ROOT = Path(__file__).resolve().parents[1]


class ListedRefresh(unittest.TestCase):
    def test_us_listed_filters_non_us_tickers(self):
        rows = us_listed()
        self.assertTrue(any(r["company_id"] == "microsoft" for r in rows))
        self.assertFalse(any(r["company_id"] == "cambricon" for r in rows))
        self.assertTrue(all(r["symbol"] for r in rows))

    def test_normalize_quote(self):
        info = {
            "symbol": "MSFT",
            "marketStatus": "Closed",
            "primaryData": {
                "lastSalePrice": "$100.50",
                "lastTradeTimestamp": "Oct 24, 2026 16:00 ET",
                "netChange": "+1.25",
                "percentageChange": "+1.26%",
            },
        }
        summary = {"symbol": "MSFT", "summaryData": {"MarketCap": {"value": "$1,000,000,000"}}}
        value = normalize("MSFT", info, summary)
        self.assertEqual(value["price"], 100.5)
        self.assertEqual(value["market_cap"], 1_000_000_000.0)

    def test_ir_adapter_packages_identity(self):
        source = {
            "company_id": "amd",
            "title": "AMD investor relations",
            "url": "https://ir.amd.com/",
        }
        rows = IrAdapter().extract(b"<html><body>AMD investors</body></html>", source, None, None)
        self.assertEqual(rows[0]["metric"], "disclosure.ir.landing")
        self.assertEqual(rows[0]["links"]["document_url"], "https://ir.amd.com/")

    def test_specs_overlap(self):
        status = specs_status()
        ids = {r["company_id"] for r in status["records"]}
        self.assertEqual(ids, set(SPEC_OVERLAP))


if __name__ == "__main__":
    unittest.main()
