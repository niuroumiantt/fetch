"""Build an immutable delivery package under a team data root.

Provides a frozen envelope; provides no transport, reception, or adoption.
Identical delivery_id + intent must replay byte-for-byte; a changed intent is refused.
"""
from __future__ import annotations

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


def _normalize_item(raw):
    fmt = raw["format"].lower()
    if fmt not in FORMATS:
        raise ValueError("unsupported format")
    sha = raw["sha256"]
    if not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("invalid sha256")
    source = raw.get("source")
    if not isinstance(source, dict):
        source = {
            "url": raw["url"],
            "publisher": raw.get("publisher") or "",
            "language": raw.get("language", "en_or_unmarked"),
            "categories": raw.get("categories") or [],
        }
    if not source.get("url"):
        raise ValueError("source.url required")
    item = {
        "source_item_id": raw["source_item_id"],
        "source": source,
        "retrieved_at": raw["retrieved_at"],
        "sha256": sha,
        "path": "files/" + sha[:2] + "/" + sha + "." + fmt,
        "bytes": raw["bytes"],
        "content_type": raw["content_type"],
        "format": fmt,
        "access_scope": raw.get("access_scope") if isinstance(raw.get("access_scope"), dict)
        else {"state": raw.get("access_scope", "public")},
        "completeness": raw.get("completeness") if isinstance(raw.get("completeness"), dict)
        else {"state": raw.get("completeness", "complete"), "basis": "SHA verified local source snapshot"},
        "version_relation": raw.get("version_relation") or {"type": "original"},
    }
    if item["retrieved_at"] is None:
        if not raw.get("reused_at") or not raw.get("provenance_id"):
            raise ValueError("reuse requires reused_at and provenance_id")
        item["reused_at"] = raw["reused_at"]
        item["provenance_id"] = raw["provenance_id"]
    for key in ("target_ids", "part_ids", "product_ids", "product_evidence", "source_observations", "title"):
        if key in raw:
            item[key] = raw[key]
    return item


def build(team, items, data_root, *, delivery_id=None, revision=None, observations=None,
          extras=None, already_locked=False):
    """Write deliveries/<delivery_id>/. Originals must already exist in Store.

    Pass already_locked=True when the caller already holds Store.lock() (e.g. collect).
    """
    if team not in TEAMS:
        raise ValueError("unknown provider")
    if not isinstance(items, list) or not items or len(items) > 10_000:
        raise ValueError("a nonempty, bounded item list is required")
    store = Store(data_root)
    revision = revision or collector_revision()
    prepared = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("item must be an object")
        item = _normalize_item(raw)
        original = store.original(item["sha256"], item["format"])
        if not original.is_file() or digest_file(original) != item["sha256"]:
            raise ValueError("original missing or hash mismatch")
        if original.stat().st_size != item["bytes"]:
            raise ValueError("declared bytes mismatch")
        if not matches(original, item["format"]):
            raise ValueError("declared format does not match bytes")
        prepared.append(item)
    intent = {"provider_id": team, "collector_revision": revision, "items": prepared,
              "observations": observations or [], "extras": extras or {}}
    intent_sha = digest(_canonical(intent))
    delivery_id = delivery_id or (team + "-" + intent_sha[:24])
    if not DELIVERY_ID.fullmatch(delivery_id) or delivery_id in {".", ".."}:
        raise ValueError("invalid delivery_id")
    package = store.root / "deliveries" / delivery_id

    def _write():
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
                "task_id_or_discovery": (extras or {}).get("task_id_or_discovery", "discovery"),
                "files_included": True,
                "acceptance": "candidate",
                "intent_sha256": intent_sha,
                "items": prepared,
            }
            if extras:
                for key, value in extras.items():
                    if key != "task_id_or_discovery":
                        manifest[key] = value
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

    if already_locked:
        return _write()
    with store.lock():
        return _write()
