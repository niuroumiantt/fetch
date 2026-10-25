"""CLI entry. Provides offline config/package/target tools; provides no scheduler or adoption."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from fetch import ROOT, TEAMS
from fetch.config import check_all, load_sources, select
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
        ROOT / "src/fetch/collect.py",
        ROOT / "src/fetch/teams" / team,
        ROOT / "src/fetch/teams/base.py",
        ROOT / "config" / team,
        ROOT / "profiles",
        ROOT / "seeds" / team,
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

    run = sub.add_parser("run", help="acquire registered source(s); no schedule")
    run.add_argument("--team", required=True, choices=TEAMS)
    run.add_argument("--source-id", help="one source; default = every registered source")
    run.add_argument("--discovered", action="store_true",
                     help="collect from discoveries/current.json instead of config")
    run.add_argument("--company-id", help="with --discovered, limit to one company_id")
    run.add_argument("--data-root")
    run.add_argument("--existing", help="reuse local bytes instead of network")
    run.add_argument("--provenance", help="required with --existing")
    run.add_argument("--history-root", help="read-only old deliveries root")
    run.add_argument("--no-robots", action="store_true", help="skip robots (tests/fixtures only)")

    sync = sub.add_parser("sync-targets", help="freeze pinned InResearch targets; no collection")
    sync.add_argument("--upstream", required=True)
    sync.add_argument("--ref", required=True, help="full reviewed InResearch commit SHA")
    sync.add_argument("--expected-sha256", required=True)
    sync.add_argument("--snapshot-root",
                      default=str(Path.home() / ".local/share/fetch/research-targets"))

    drain_cmd = sub.add_parser(
        "drain-requests",
        help="claim website run queue on this collector; outbound crawl stays local")
    drain_cmd.add_argument("--api-base", required=True,
                           help="inresearch origin, e.g. https://www.inresearch.ai")
    drain_cmd.add_argument("--token", help="collector bearer; or INRESEARCH_FETCH_RUNS_TOKEN")
    drain_cmd.add_argument("--collector-host", help="short host id written into claim")
    drain_cmd.add_argument("--data-root", help="override ~/.local/share/fetch/<team>")
    drain_cmd.add_argument("--limit", type=int, default=20)
    drain_cmd.add_argument("--no-robots", action="store_true", help="tests/fixtures only")

    discover_cmd = sub.add_parser(
        "discover",
        help="discover latest SEC periodic filings for listed companies; no adoption")
    discover_cmd.add_argument("--team", required=True, choices=("fetchfilings",))
    discover_cmd.add_argument("--company-id", help="one listed company_id; default = all sec_edgar")
    discover_cmd.add_argument("--data-root", help="override ~/.local/share/fetch/fetchfilings")
    discover_cmd.add_argument("--no-robots", action="store_true", help="tests/fixtures only")

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
            load_sources(args.team)
            _print(_release(args.team))
            return 0
        if args.command == "run":
            from fetch.collect import collect
            data = (Path(args.data_root).expanduser() if args.data_root
                    else Path.home() / ".local/share/fetch" / args.team)
            if args.discovered:
                if args.team != "fetchfilings":
                    raise ValueError("--discovered is only for fetchfilings")
                if args.source_id:
                    raise ValueError("--discovered cannot combine with --source-id")
                from fetch.teams.fetchfilings.discover import discovered_sources
                sources = discovered_sources(data, company_id=args.company_id)
                if not sources:
                    raise ValueError("no discovered sources to collect")
            else:
                if args.company_id:
                    raise ValueError("--company-id requires --discovered")
                sources = select(load_sources(args.team), args.source_id)
            if args.existing and len(sources) != 1:
                raise ValueError("--existing requires exactly one --source-id")
            results = [collect(source, data, local=args.existing, provenance=args.provenance,
                               history_root=args.history_root, respect_robots=not args.no_robots)
                       for source in sources]
            _print(results[0] if len(results) == 1 else results)
            return 0
        if args.command == "sync-targets":
            from fetch.targets import freeze
            _print(freeze(args.upstream, args.ref, args.expected_sha256, args.snapshot_root))
            return 0
        if args.command == "drain-requests":
            import os
            from fetch.drain import drain
            token = args.token or os.environ.get("INRESEARCH_FETCH_RUNS_TOKEN", "")
            _print(drain(
                args.api_base, token,
                collector_host=args.collector_host,
                data_root=args.data_root,
                limit=args.limit,
                respect_robots=not args.no_robots))
            return 0
        if args.command == "discover":
            from fetch.teams.fetchfilings.discover import discover
            _print(discover(
                data_root=args.data_root,
                company_id=args.company_id,
                respect_robots=not args.no_robots))
            return 0
        raise ValueError("unknown command")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        failure = dict(at=now(), **classify(error, args.command))
        if getattr(args, "team", None):
            failure["provider_id"] = args.team
        _print(failure, stream=sys.stderr)
        return 1
