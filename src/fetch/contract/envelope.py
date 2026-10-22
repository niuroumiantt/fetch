"""Offline package validation. Never an HTTP receiver or adoption gate.

Accepts the production fetchspec 2.0 item shape (nested source, access_scope dict)
and the observation-team shape (same envelope + optional observations.jsonl).
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

from fetch import TEAMS
from fetch.core.formats import FORMATS

CONTRACT_VERSION = "2.0"
SHA = re.compile(r"[a-f0-9]{64}\Z")
# Historical packages may record an uncommitted working tree as "<40hex>-dirty".
REVISION = re.compile(r"[0-9a-f]{40}(?:-dirty)?\Z")
DELIVERY_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
MAX_METADATA = 4 * 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_ROWS = 100_000
MAX_ITEMS = 10_000
KINDS = frozenset({"reported", "measured", "estimated", "calculated", "forecast", "offer"})
OBJECT_TYPES = frozenset({"site", "company", "product", "statistic_series", "study"})
FORBIDDEN_SUPPLIER = frozenset({"first_received_at", "adopted", "verified_date", "reviewed_at"})


def _file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("invalid relative path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(p in {".", ".."} for p in relative.split("/")):
        raise ValueError("unsafe relative path")
    candidate = root
    for part in parts.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("symlink is not a package file")
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("package file missing or outside root")
    return candidate


def _json(root: Path, relative: str):
    path = _file(root, relative)
    if path.stat().st_size > MAX_METADATA:
        raise ValueError("metadata too large")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)


def _reject_nonfinite(value):
    raise ValueError("non-finite JSON number")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value):
    try:
        return (isinstance(value, str) and "T" in value
                and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None)
    except ValueError:
        return False


def _time(value):
    if not isinstance(value, dict):
        return False
    precision, raw = value.get("precision"), value.get("value")
    if precision == "unknown":
        return raw is None
    if not _text(value.get("basis")) or not isinstance(raw, str):
        return False
    try:
        if precision == "year":
            return bool(re.fullmatch(r"[0-9]{4}", raw)) and 1 <= int(raw) <= 9999
        if precision == "month":
            return bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}", raw)) and bool(date.fromisoformat(raw + "-01"))
        if precision == "day":
            return bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw)) and bool(date.fromisoformat(raw))
        return precision == "datetime" and _timestamp(raw)
    except ValueError:
        return False


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _rows(root: Path, relative: str):
    path = root / relative
    if not path.exists():
        return
    with _file(root, relative).open("rb") as stream:
        for index in range(1, MAX_ROWS + 2):
            raw = stream.readline(MAX_LINE + 1)
            if not raw:
                return
            if index > MAX_ROWS or len(raw) > MAX_LINE:
                raise ValueError("JSONL row/line limit exceeded")
            try:
                yield index, json.loads(raw, parse_constant=_reject_nonfinite)
            except (ValueError, UnicodeError):
                yield index, None


def _source_url(item):
    source = item.get("source")
    if isinstance(source, dict) and _text(source.get("url")):
        return source["url"]
    if _text(item.get("url")):
        return item["url"]
    return None


def _access_state(item):
    scope = item.get("access_scope", "public")
    if isinstance(scope, dict):
        return scope.get("state")
    return scope


def _observation_errors(row, source_item_ids):
    if not isinstance(row, dict):
        return ["invalid JSON object"]
    errors = []
    if not _text(row.get("observation_id")) or row.get("source_item_id") not in source_item_ids:
        errors.append("missing ID or dangling source reference")
    obj = row.get("object") if isinstance(row.get("object"), dict) else {}
    if (obj.get("type") not in OBJECT_TYPES or not _text(obj.get("name"))
            or not isinstance(obj.get("identifiers", {}), dict)):
        errors.append("object identity shape invalid")
    if obj.get("match_status") == "matched":
        if not _text(obj.get("canonical_id")) or not _text(obj.get("match_basis")):
            errors.append("matched object requires ID and basis")
    elif obj.get("match_status") != "unresolved" or obj.get("canonical_id") is not None:
        errors.append("unresolved object must not claim a canonical ID")
    if not _text(row.get("metric")) or not _text(row.get("scope")):
        errors.append("metric/scope missing")
    if row.get("kind") not in KINDS:
        errors.append("kind invalid")
    value = row.get("value") if isinstance(row.get("value"), dict) else {}
    typ = value.get("type")
    ok = ((typ == "number" and _number(value.get("number")))
          or (typ == "range" and _number(value.get("lower")) and _number(value.get("upper"))
              and value["lower"] <= value["upper"])
          or (typ == "text" and _text(value.get("text"))))
    if not ok or not _text(value.get("raw")):
        errors.append("value/raw invalid")
    if (typ in {"number", "range"} and not _text(row.get("unit"))) or "unit" not in row:
        errors.append("numeric unit missing")
    for key in ("effective_time", "published_time"):
        if not _time(row.get(key)):
            errors.append(key + " invalid")
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    if any(not _text(evidence.get(k)) for k in ("locator", "quote", "context")):
        errors.append("evidence location/quote/context missing")
    if "revision_of" not in row or not (row["revision_of"] is None or _text(row["revision_of"])):
        errors.append("revision_of invalid")
    for key in ("conflicts_with", "target_ids"):
        values = row.get(key, [] if key == "target_ids" else None)
        if not isinstance(values, list) or any(not _text(v) for v in values):
            errors.append(key + " invalid")
    if FORBIDDEN_SUPPLIER & set(row):
        errors.append("supplier cannot assert reception/review/adoption")
    return errors


def validate(package):
    """Return a report. `offline_valid` is True only when every check passes."""
    root = Path(package).expanduser().resolve(strict=True)
    errors, invalid, source_item_ids, paths = [], [], set(), {}
    manifest = _json(root, "manifest.json")
    if (not isinstance(manifest, dict) or manifest.get("contract_version") != CONTRACT_VERSION
            or manifest.get("provider_id") not in TEAMS or not _text(manifest.get("delivery_id"))
            or not DELIVERY_ID.fullmatch(manifest["delivery_id"])
            or not isinstance(manifest.get("collector_revision"), str)
            or not REVISION.fullmatch(manifest["collector_revision"])
            or manifest.get("files_included") is not True):
        raise ValueError("manifest identity/version invalid")
    items = manifest.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise ValueError("items must contain 1..10000 source records")
    for index, item in enumerate(items):
        label = "item[" + str(index) + "]"
        try:
            if not isinstance(item, dict):
                raise ValueError("item is not an object")
            if not _text(item.get("source_item_id")) or not _text(item.get("content_type")):
                raise ValueError("source_item_id/content_type missing")
            if item["source_item_id"] in source_item_ids:
                raise ValueError("duplicate source_item_id")
            source_item_ids.add(item["source_item_id"])
            fmt = item.get("format")
            if not isinstance(fmt, str) or fmt.lower() not in FORMATS:
                raise ValueError("unsupported format")
            fmt = fmt.lower()
            url = _source_url(item)
            parsed = urlsplit(url or "")
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("source URL missing or credentialed")
            if "retrieved_at" not in item or (item["retrieved_at"] is not None and not _timestamp(item["retrieved_at"])):
                raise ValueError("retrieved_at invalid")
            if item["retrieved_at"] is None and (
                    not _timestamp(item.get("reused_at")) or not _text(item.get("provenance_id"))):
                raise ValueError("unknown old download needs reuse time and provenance")
            if _access_state(item) not in {"public", "restricted", "unknown"}:
                raise ValueError("access_scope invalid")
            sha, relative = item.get("sha256"), item.get("path")
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise ValueError("SHA invalid")
            expected = "files/" + sha[:2] + "/" + sha + "." + fmt
            if relative != expected:
                raise ValueError("original must use content-addressed files/ path")
            path = _file(root, relative)
            if type(item.get("bytes")) is not int or item["bytes"] < 0:
                raise ValueError("bytes invalid")
            if path.stat().st_size != item["bytes"]:
                raise ValueError("declared bytes mismatch")
            if relative not in paths:
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(block)
                if hasher.hexdigest() != sha:
                    raise ValueError("SHA mismatch")
                paths[relative] = sha
        except (ValueError, TypeError, OSError) as error:
            errors.append(label + ": " + str(error))
    sums = _file(root, "SHA256SUMS")
    if sums.stat().st_size > MAX_METADATA:
        raise ValueError("checksum metadata too large")
    lines = [line for line in sums.read_text(encoding="ascii").splitlines() if line]
    if sorted(lines) != sorted(sha + "  " + name for name, sha in paths.items()):
        errors.append("SHA256SUMS differs from unique manifest files")
    observation_ids, total = set(), 0
    for line, row in _rows(root, "observations.jsonl"):
        total += 1
        issues = _observation_errors(row, source_item_ids)
        if isinstance(row, dict) and _text(row.get("observation_id")):
            if row["observation_id"] in observation_ids:
                issues.append("duplicate observation_id")
            observation_ids.add(row["observation_id"])
        if issues:
            invalid.append({"line": line, "errors": issues})
    return {
        "contract_version": CONTRACT_VERSION,
        "delivery_id": manifest["delivery_id"],
        "provider_id": manifest["provider_id"],
        "source_items": len(items),
        "unique_originals": len(paths),
        "candidate_rows": total,
        "valid_candidate_rows": total - len(invalid),
        "package_errors": errors,
        "invalid_candidates": invalid,
        "offline_valid": not errors and not invalid,
        "formal_adoption": False,
    }
