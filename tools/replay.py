#!/usr/bin/env python3
"""Offline package replay: new validator must accept a frozen package directory.

Usage:
  PYTHONPATH=src python3 tools/replay.py --team fetchstat path/to/delivery-...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fetch import TEAMS  # noqa: E402
from fetch.contract.envelope import validate  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", required=True, choices=TEAMS)
    parser.add_argument("package")
    args = parser.parse_args(argv)
    report = validate(Path(args.package))
    if report["provider_id"] != args.team:
        report = {**report, "offline_valid": False,
                  "package_errors": report.get("package_errors", []) + ["package/provider mismatch"]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["offline_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
