"""Replay: new validator must accept a frozen production fetchspec package when present."""
import os
import unittest
from pathlib import Path

from fetch.contract.envelope import validate

LEGACY = Path(os.path.expanduser(
    "~/.local/share/fetchspec/pipeline/deliveries/fetchspec-asteralabs-e13ececae13b6caa632522d4"))


class ReplayPackages(unittest.TestCase):
    @unittest.skipUnless(LEGACY.is_dir(), "local asteralabs delivery not present")
    def test_production_fetchspec_package_offline_valid(self):
        report = validate(LEGACY)
        self.assertTrue(report["offline_valid"], report["package_errors"])
        self.assertEqual(report["provider_id"], "fetchspec")
        self.assertGreaterEqual(report["source_items"], 1)


if __name__ == "__main__":
    unittest.main()
