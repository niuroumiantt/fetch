"""Build an immutable delivery package under a team data root.

Provides a frozen envelope; provides no transport, reception, or adoption.
Identical delivery_id + intent must replay byte-for-byte; a changed intent is refused.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from fetch import ROOT, TEAMS
from fetch.contract.envelope import CONTRACT_VERSION, DELIVERY_ID, REVISION, validate
from fetch.core.formats import FORMATS, matches
from fetch.core.http import now
from fetch.core.store import Store, digest, digest_file, write_json

ITEM_KEYS = ("item_id", "source_id", "source_item_id", "url", "content_type", "format",
             "sha256", "bytes", "retrieved_at")


def collector_revision():
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not REVISION.fullmatch(revision):
        raise ValueError("committed collector revision required")
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty:
        raise ValueError("commit source/config before versioned packaging")
    return revision


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


def build(team, items, data_root, *, delivery_id=None, revision=None, observations=None, extras=None):
    """Write deliveries/<delivery_id>/. items are prepared dicts; originals already in Store."""
    if team not in TEAMS:
        raise ValueError("unknown provider")
    if not isinstance(items, list) or not items or len(items) > 10_000:
        raise ValueError("a nonempty, bounded item list is required")
    store = Store(data_root)
    revision = revision or collector_revision()
    prepared = []
    for raw in items:
        if not isinstance(raw, dict) or any(k not in raw for k in ITEM_KEYS):
            raise ValueError("item missing required fields")
        fmt = raw["format"]
        if fmt not in FORMATS:
            raise ValueError("unsupported format")
        sha = raw["sha256"]
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("invalid sha256")
        original = store.original(sha, fmt)
        if not original.is_file() or digest_file(original) != sha:
            raise ValueError("original missing or hash mismatch")
        if original.stat().st_size != raw["bytes"]:
            raise ValueError("declared bytes mismatch")
        if not matches(original, fmt):
            raise ValueError("declared format does not match bytes")
        relative = "files/" + sha[:2] + "/" + sha + "." + fmt
        item = {
            "item_id": raw["item_id"],
            "source_id": raw["source_id"],
            "source_item_id": raw["source_item_id"],
            "url": raw["url"],
            "title": raw.get("title") or raw["source_item_id"],
            "publisher": raw.get("publisher") or team,
            "retrieved_at": raw["retrieved_at"],
            "sha256": sha,
            "path": relative,
            "bytes": raw["bytes"],
            "content_type": raw["content_type"],
            "format": fmt,
            "access_scope": raw.get("access_scope", "public"),
            "completeness": raw.get("completeness", "complete"),
            "version_of": raw.get("version_of"),
        }
        if item["retrieved_at"] is None:
            if not raw.get("reused_at") or not raw.get("provenance_id"):
                raise ValueError("reuse requires reused_at and provenance_id")
            item["reused_at"] = raw["reused_at"]
            item["provenance_id"] = raw["provenance_id"]
        prepared.append(item)
    intent = {"provider_id": team, "collector_revision": revision, "items": prepared,
              "observations": observations or [], "extras": extras or {}}
    intent_sha = digest(_canonical(intent))
    delivery_id = delivery_id or (team + "-" + intent_sha[:24])
    if not DELIVERY_ID.fullmatch(delivery_id) or delivery_id in {".", ".."}:
        raise ValueError("invalid delivery_id")
    package = store.root / "deliveries" / delivery_id
    with store.lock():
        if package.exists():
            report = validate(package)
            prior = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            if prior.get("intent_sha256") != intent_sha or not report["offline_valid"]:
                raise ValueError("delivery_id reused with different or invalid content")
            return {"delivery_id": delivery_id, "package": str(package), "replayed": True, **report}
        package.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="." + delivery_id + "-", dir=package.parent) as temp:
            stage = Path(temp) / "package"
            stage.mkdir()
            for item in prepared:
                destination = stage / item["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(store.original(item["sha256"], item["format"]), destination)
                with destination.open("rb") as stream:
                    os.fsync(stream.fileno())
            manifest = {
                "contract_version": CONTRACT_VERSION,
                "provider_id": team,
                "delivery_id": delivery_id,
                "collector_revision": revision,
                "collector_repository": "fetch",
                "created_at": now(),
                "files_included": True,
                "acceptance": "candidate",
                "intent_sha256": intent_sha,
                "items": prepared,
            }
            if extras:
                manifest.update(extras)
            write_json(stage / "manifest.json", manifest)
            (stage / "SHA256SUMS").write_text(
                "".join(item["sha256"] + "  " + item["path"] + "\n" for item in prepared), encoding="ascii")
            if observations:
                (stage / "observations.jsonl").write_text(
                    "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observations),
                    encoding="utf-8")
            report = validate(stage)
            if not report["offline_valid"]:
                raise ValueError(json.dumps(report, ensure_ascii=False))
            os.rename(stage, package)
        return {"delivery_id": delivery_id, "package": str(package), "replayed": False, **report}
