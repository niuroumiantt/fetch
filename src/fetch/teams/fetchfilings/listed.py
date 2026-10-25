"""Load the frozen listed-company universe for fetchfilings.

Provides company_id / CIK / channel rows for discovery. Provides no filing
facts and does not invent CIKs for local_ir companies.
"""
from __future__ import annotations

import json

from fetch import ROOT

SEED = ROOT / "seeds" / "fetchfilings" / "listed_companies.json"


def load_listed(path=None):
    value = json.loads((path or SEED).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("records"), list):
        raise ValueError("listed_companies seed malformed")
    return value


def sec_edgar_companies(path=None):
    """Companies that must be discovered via SEC submissions (channel + CIK)."""
    rows = []
    for row in load_listed(path)["records"]:
        if row.get("channel") != "sec_edgar":
            continue
        cik = (row.get("cik") or "").strip()
        if not cik:
            raise ValueError("sec_edgar company missing cik: " + row.get("company_id", "?"))
        rows.append(row)
    return rows


def local_ir_companies(path=None):
    """Listed companies without SEC CIK; official IR / local exchange only."""
    return [row for row in load_listed(path)["records"] if row.get("channel") == "local_ir"]
