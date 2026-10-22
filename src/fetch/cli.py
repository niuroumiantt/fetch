"""CLI entry. Provides offline config/package/target tools; provides no scheduler or adoption."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from fetch import ROOT, TEAMS
from fetch.config import check_all, load_sources
from fetch.contract.envelope import validate
from fetch.core.failures import classify
from fetch.core.http import now


def _print(value, *, stream=sys.stdout):
    print(json.dumps(value, ensure_ascii=False, indent=2), file=stream)


def _release(team):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty:
        raise ValueError("commit source/config before versioned release")
    paths = [
        ROOT / "src/fetch/core",
        ROOT / "src/fetch/contract",
        ROOT / "src/fetch/teams" / team,
        ROOT / "src/fetch/teams/base.py",
        ROOT / "config" / team,
    ]
    files = sorted(
        path for base in paths if base.exists()
        for path in (base.rglob("*") if base.is_dir() else [base])
        if path.is_file() and "__pycache__" not in path.parts)
    return {
        "repository": "fetch",
        "revision": revision,
        "provider_id": team,
        "contract_version": "2.0",
        "files": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in files},
        "deployment_unit": "whole committed checkout + one provider",
        "scheduled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-config", help="validate registered sources")
    check.add_argument("--team", choices=TEAMS)

    verify = sub.add_parser("verify", help="offline package validation")
    verify.add_argument("--team", required=True, choices=TEAMS)
    verify.add_argument("package")

    release = sub.add_parser("release", help="version manifest for one team")
    release.add_argument("--team", required=True, choices=TEAMS)

    sync = sub.add_parser("sync-targets", help="freeze pinned InResearch targets; no collection")
    sync.add_argument("--upstream", required=True)
    sync.add_argument("--ref", required=True, help="full reviewed InResearch commit SHA")
    sync.add_argument("--expected-sha256", required=True)
    sync.add_argument("--snapshot-root",
                      default=str(Path.home() / ".local/share/fetch/research-targets"))

    args = parser.parse_args(argv)
    try:
        if args.command == "check-config":
            if args.team:
                sources = load_sources(args.team)
                result = dict(provider_id=args.team, source_ids=[s["id"] for s in sources],
                              scheduled=any(s.get("scheduled") for s in sources),
                              model_required=False)
            else:
                result = check_all()
            _print(result)
            return 0
        if args.command == "verify":
            report = validate(Path(args.package))
            if report["provider_id"] != args.team:
                raise ValueError("package/provider mismatch")
            _print(report)
            return 0 if report["offline_valid"] else 1
        if args.command == "release":
            load_sources(args.team)  # config must parse
            _print(_release(args.team))
            return 0
        if args.command == "sync-targets":
            from fetch.targets import freeze
            _print(freeze(args.upstream, args.ref, args.expected_sha256, args.snapshot_root))
            return 0
        raise ValueError("unknown command")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = dict(at=now(), **classify(error, args.command))
        if getattr(args, "team", None):
            failure["provider_id"] = args.team
        _print(failure, stream=sys.stderr)
        return 1
