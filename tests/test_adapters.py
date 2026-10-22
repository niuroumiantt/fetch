"""Frozen-fixture extractors: same synthetic HTML as the prior fetchdata bootstrap."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fetch import TEAMS
from fetch.collect import collect
from fetch.config import load_sources
from fetch.contract.envelope import validate


def bootstrap(team):
    return next(source for source in load_sources(team) if "bootstrap" in source["id"]
                or source["id"].endswith("pt6162lx"))


def fixture(team):
    if team == "fetchstat":
        row = "<tr>" + "".join("<td>" + x + "</td>" for x in
                               ["Texas", "1", "2", "3", "4", "7.5", "6", "7", "8", "9", "10"]) + "</tr>"
        return ("<html>Year-to-Date through July 2026 and 2025 Release Date: October 1, 2026 "
                "Industrial Cents per Kilowatthour<table>" + row + "</table></html>").encode()
    if team == "fetchfilings":
        return (b"<html>Year Ended June 30, 2025 2024 2023 (In millions)<table>"
                b"<tr><td>Additions to property and equipment</td>"
                b"<td>(64,551)</td><td>(44,477)</td><td>(28,107)</td></tr></table></html>")
    if team == "fetchreports":
        return (b"<html>This report, designed for a SYNTHETIC test, uses historical shipment data. "
                b"Date Published 12/19/2024 10.71468/P1WC7Q</html>")
    if team == "fetchquotes":
        table = ("<html><p>PRICE/GPU/HR* plus applicable sales tax/VAT/GST</p><table><tr>"
                 + "".join("<td>" + x + "</td>" for x in
                           ["NVIDIA H100 SXM", "80 GB", "26", "200 GiB", "1 TB", "$2.49"])
                 + "</tr></table></html>")
        return ("<html><script>var newIslands = " + json.dumps(
            [{"props": {"tabs": [{"label": "1x", "contentHtml": table}]}}])
                + ";</script></html>").encode()
    # fetchspec asteralabs part page (shape observed 2026-10-01)
    brief = "https://www.asteralabs.com/wp-content/uploads/2025/05/PB_Aries_PCIe_CXL_Smart_DSP_Retimers.pdf"
    return ("<html><body><h1 class=\"h2\">PT6162LX</h1>"
            "<p>Astera Labs CXL/PCIe 5.0 x8 Low-Latency Smart Retimer</p>"
            "<a href=\"" + brief + "\" download>Product brief</a>"
            "<ul class=\"list-unstyled\">"
            "<li> <span class=\"fw-medium\"> Package: </span> 354-pin FC-CSP </li>"
            "<li> <span class=\"fw-medium\"> Max PCIe Gen: </span> PCIe 6.x / CXL 3.x </li>"
            "<li> <span class=\"fw-medium\"> Retimer Generation: </span> 3<sup>rd</sup> </li>"
            "<li class=\"d-flex\"> <span class=\"fw-medium d-inline-block\"> Pack Quantity: </span> "
            "<p>240, 2400</p> </li></ul></body></html>").encode()


class Adapters(unittest.TestCase):
    def test_five_native_extractors_and_stable_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            for team in TEAMS:
                source = bootstrap(team)
                native = Path(tmp) / (team + ".html")
                native.write_bytes(fixture(team))
                with mock.patch("fetch.collect.collector_revision", return_value="a" * 40):
                    result = collect(source, Path(tmp) / team, local=native,
                                     provenance="SYNTHETIC test only", revision="a" * 40,
                                     respect_robots=False)
                package = Path(result["package"])
                self.assertTrue(validate(package)["offline_valid"])
                rows = [json.loads(line) for line in
                        (package / "observations.jsonl").read_text().splitlines() if line]
                sha = hashlib.sha256(native.read_bytes()).hexdigest()
                self.assertEqual(result["delivery_id"], team + "-" + sha[:24] + "-v1")
                self.assertTrue(rows)
                self.assertEqual(rows[0]["source_item_id"], source["id"] + ":" + sha[:24])
                self.assertIsNone(rows[0]["object"]["canonical_id"])
                if team == "fetchquotes":
                    self.assertIsNone(rows[0]["object"]["identifiers"]["currency"])
                elif team == "fetchfilings":
                    self.assertEqual(rows[0]["value"]["number"], -64551)
                elif team == "fetchstat":
                    self.assertEqual(rows[0]["aggregation"], "year_to_date")
                elif team == "fetchreports":
                    self.assertEqual(rows[0]["metric"], "study.method")
                else:
                    self.assertEqual(rows[0]["object"]["identifiers"]["company_id"], "asteralabs")
                    self.assertGreaterEqual(len(rows), 4)


if __name__ == "__main__":
    unittest.main()
