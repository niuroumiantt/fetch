"""Weekly refresh for the listed-company filings universe.

Discovers SEC periodic filings, collects primary documents, and writes a
disclosures projection. Provides no adoption and does not invent CIKs for
local_ir companies.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fetch import ROOT
from fetch.collect import collect
from fetch.core.failures import classify
from fetch.core.http import now
from fetch.teams.fetchfilings.discover import discover, discovered_sources
from fetch.teams.fetchfilings.disclosures import write_disclosures
from fetch.teams.fetchfilings.listed import load_listed, local_ir_companies


def _head_revision():
    """Committed HEAD only — weekly refresh must not block on a dirty worktree."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def refresh(*, data_root=None, company_id=None, listed_path=None, respect_robots=True,
            collect_filings=True, prior_disclosures=None):
    root = Path(data_root).expanduser() if data_root else Path.home() / ".local/share/fetch/fetchfilings"
    started = now()
    listed = load_listed(listed_path)
    cadence = (listed.get("policy") or {}).get("scheduled_phase") or "weekly"
    revision = _head_revision()

    discovery = discover(
        data_root=root, company_id=company_id, listed_path=listed_path,
        respect_robots=respect_robots)

    collections = []
    if collect_filings:
        sources = discovered_sources(root, company_id=company_id)
        for source in sources:
            try:
                result = collect(source, root, respect_robots=respect_robots, revision=revision)
                collections.append({
                    "source_id": source["id"],
                    "outcome": "success",
                    "delivery_id": result.get("delivery_id"),
                    "replayed": bool(result.get("replayed")),
                    "package": result.get("package"),
                })
            except (OSError, ValueError, TypeError, KeyError) as error:
                collections.append({
                    "source_id": source["id"],
                    "outcome": "failure",
                    "failure": classify(error, "refresh"),
                })

    disclosures = write_disclosures(
        root, listed_path=listed_path, prior_path=prior_disclosures)

    local_ir = local_ir_companies(listed_path)
    if company_id:
        local_ir = [c for c in local_ir if c["company_id"] == company_id]

    return {
        "team": "fetchfilings",
        "cadence": cadence,
        "started_at": started,
        "finished_at": now(),
        "path": str(root),
        "discovery": {
            "path": discovery.get("path"),
            "counts": discovery.get("counts"),
        },
        "collection": {
            "attempted": len(collections),
            "success": sum(1 for r in collections if r["outcome"] == "success"),
            "failure": sum(1 for r in collections if r["outcome"] == "failure"),
            "replayed": sum(1 for r in collections if r.get("replayed")),
            "results": collections,
        },
        "disclosures": {
            "path": disclosures.get("path"),
            "counts": disclosures.get("counts"),
        },
        "local_ir": {
            "companies": len(local_ir),
            "with_ir_url": sum(1 for c in local_ir if (c.get("ir_url") or "").startswith("https://")),
            "note": "official IR / local exchange only; no invented SEC CIK",
        },
    }
