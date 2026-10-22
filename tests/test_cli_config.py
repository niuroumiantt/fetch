import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliConfig(unittest.TestCase):
    def test_check_config_all_teams(self):
        result = subprocess.run(
            ["python3", "fetch", "check-config"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {
            "fetchspec", "fetchstat", "fetchfilings", "fetchreports", "fetchquotes"})
        for team, info in payload.items():
            self.assertEqual(info["provider_id"], team)
            self.assertEqual(info["source_ids"], [])
            self.assertFalse(info["scheduled"])


if __name__ == "__main__":
    unittest.main()
