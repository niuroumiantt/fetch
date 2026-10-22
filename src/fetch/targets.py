"""Freeze reviewed InResearch demand metadata. Never collects or authorizes sources."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from fetch import TEAMS

CONTRACT = "fetch-research-targets/1"
REPOSITORY = "niuroumiantt/inresearch.ai"
SOURCE_FILE = "framework/tco_targets.json"
MAX_BYTES = 16 * 1024 * 1024
TARGET_ID = re.compile(r"[FPS]\.[A-Za-z0-9_.-]{1,198}")
REVISION = re.compile(r"[0-9a-f]{40}")
SHA = re.compile(r"[a-f0-9]{64}")
SOURCE_TEAMS = set(TEAMS) | {"inews"}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def _git(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if result.returncode:
        raise ValueError("cannot read pinned InResearch Git source")
    return result.stdout


def read_source(upstream, revision, expected_sha256):
    if not REVISION.fullmatch(revision or "") or not SHA.fullmatch(expected_sha256 or ""):
        raise ValueError("full source commit and expected file SHA256 required")
    root = Path(upstream).expanduser().resolve()
    origin = _git(root, "remote", "get-url", "origin").decode().strip()
    matched = re.fullmatch(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^?#\s]+)", origin)
    if not matched or matched[1].removesuffix(".git").lower() != REPOSITORY.lower():
        raise ValueError("only the registered InResearch source repository is accepted")
    if _git(root, "rev-parse", revision + "^{commit}").decode().strip() != revision:
        raise ValueError("source revision must be a commit")
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(["git", "-C", str(root), "show", revision + ":" + SOURCE_FILE],
                                stdout=output, stderr=subprocess.PIPE, timeout=30)
        output.seek(0)
        raw = output.read(MAX_BYTES + 1)
    if result.returncode or len(raw) > MAX_BYTES or digest(raw) != expected_sha256:
        raise ValueError("pinned target file missing, too large or SHA256 mismatch")
    document = json.loads(raw)
    if (not isinstance(document, dict) or not isinstance(document.get("targets"), list)
            or not document["targets"]):
        raise ValueError("invalid InResearch target document")
    ids = set()
    for row in document["targets"]:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not TARGET_ID.fullmatch(row["id"]) or row["id"] in ids):
            raise ValueError("invalid or duplicate target ID")
        if row.get("team") not in SOURCE_TEAMS:
            raise ValueError("unknown target team: " + str(row.get("team")))
        ids.add(row["id"])
    source = dict(repository=REPOSITORY, revision=revision, path=SOURCE_FILE,
                  sha256=expected_sha256, target_version=document.get("version"),
                  target_updated=document.get("updated"))
    return source, raw, document


def project(source, document):
    outputs = {}
    for team in TEAMS:
        rows = [row for row in document["targets"] if row.get("team") == team]
        outputs[team] = dict(
            contract=CONTRACT, team=team, source=source,
            execution=dict(collection_enabled=False, scheduled=False, source_authorization="unchanged"),
            note="Demand metadata only. No observations or source permissions are created.",
            targets=rows, counts=dict(targets=len(rows)))
    return outputs


def freeze(upstream, revision, expected_sha256, snapshot_root):
    source, raw, document = read_source(upstream, revision, expected_sha256)
    base = Path(snapshot_root).expanduser()
    if not base.is_absolute() or base.is_symlink():
        raise ValueError("snapshot root must be an absolute regular directory")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot_id = digest(encoded(dict(contract=CONTRACT, source=source)))
    files = {"source/tco_targets.json": raw}
    files.update({"teams/" + team + ".json": encoded(value)
                  for team, value in project(source, document).items()})
    files["manifest.json"] = encoded(dict(
        contract=CONTRACT, snapshot_id=snapshot_id, source=source,
        files={name: digest(value) for name, value in files.items()},
        execution_enabled=False))
    destination = base / snapshot_id
    lock_path = base / ".targets.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists():
            present = {str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file()}
            if present != set(files) or any((destination / name).read_bytes() != value
                                            for name, value in files.items()):
                raise ValueError("frozen snapshot changed")
            return dict(snapshot_id=snapshot_id, path=str(destination), replayed=True,
                        source=source, execution_enabled=False)
        stage = Path(tempfile.mkdtemp(prefix=".targets-", dir=base))
        try:
            for name, value in files.items():
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as handle:
                    handle.write(value)
                    handle.flush()
                    os.fsync(handle.fileno())
            stage.rename(destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return dict(snapshot_id=snapshot_id, path=str(destination), replayed=False,
                source=source, execution_enabled=False)
