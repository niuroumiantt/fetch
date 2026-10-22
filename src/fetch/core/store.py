"""Content-addressed originals and the run ledger. Provides byte identity; provides no reception receipt.

Layout under one team data root:
  originals/<sha[:2]>/<sha>.<fmt>            immutable bytes, written once
  originals/<sha[:2]>/<sha>.metadata.json    first_seen_at, retrieved_at (null when reused), provenance
  acquisitions.jsonl                         every attempt, success or failure, with its own clock
  deliveries/<delivery_id>/                  packages (see fetch.contract.envelope)
  .lock                                      one writer per team root
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from fetch.core.failures import classify
from fetch.core.http import now


def digest(data):
    return hashlib.sha256(data).hexdigest()


def digest_file(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def write_json(path, value):
    """Atomic, fsynced JSON with stable bytes (ensure_ascii=False, indent=2, trailing newline)."""
    path = Path(path)
    body = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, temp = tempfile.mkstemp(prefix=".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def lock(self):
        handle = (self.root / ".lock").open("a")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle

    def original(self, sha, fmt):
        return self.root / "originals" / sha[:2] / (sha + "." + fmt)

    def put(self, data, fmt, *, retrieved_at, provenance=None):
        """Store bytes once; return (path, metadata, created). Existing bytes are verified, never rewritten."""
        sha = digest(data)
        path = self.original(sha, fmt)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        created = not path.exists()
        if created:
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        elif digest_file(path) != sha:
            raise ValueError("stored original failed hash; preserve and investigate")
        meta_path = path.with_name(sha + ".metadata.json")
        if not meta_path.exists():
            write_json(meta_path, {"sha256": sha, "format": fmt, "bytes": len(data), "first_seen_at": now(),
                                   "retrieved_at": retrieved_at, "provenance_id": provenance})
        return path, json.loads(meta_path.read_text(encoding="utf-8")), created

    def record(self, entry):
        with (self.root / "acquisitions.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record_failure(self, team, source_id, error, *, started_at, mode="live"):
        self.record({"started_at": started_at, "finished_at": now(), "provider_id": team, "source_id": source_id,
                     "mode": mode, "outcome": "failed", "failure": classify(error, "acquisition")})
