"""Acquire one registered source, extract candidates, and package. Provides no reception."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from fetch import TEAMS, USER_AGENT
from fetch.contract.package import build, collector_revision
from fetch.core.failures import FlowError
from fetch.core.http import Fetcher, now
from fetch.core.store import Store, digest


def adapter_for(team, slug=None):
    name = "fetch.teams." + team + (".adapters." + slug if slug else ".adapter")
    module = importlib.import_module(name)
    if hasattr(module, "Adapter"):
        return module.Adapter()
    if hasattr(module, "extract"):
        return module
    raise ValueError("adapter missing extract")


def _extract(adapter, data, source, original, retrieved_at):
    if hasattr(adapter, "extract") and callable(adapter.extract) and not isinstance(adapter, type):
        # Adapter instance or module with extract(data, source, original, retrieved_at)
        return adapter.extract(data, source, original, retrieved_at)
    raise ValueError("adapter extract not callable")


def collect(source, data_root, *, local=None, provenance=None, revision=None, history_root=None,
            respect_robots=True):
    """One writer per team/root. Same bytes do not rebuild the envelope."""
    team = source.get("team")
    if team not in TEAMS:
        raise ValueError("unknown provider")
    revision = revision or collector_revision()
    store = Store(data_root)
    started = now()
    with store.lock():
        try:
            if local:
                if not provenance:
                    raise ValueError("--provenance required when reusing existing bytes")
                path = Path(local).expanduser()
                data = path.read_bytes()
                content_type, url, retrieved = source["content_type"], source["url"], None
            else:
                fetcher = Fetcher(source["hosts"], respect_robots=respect_robots, user_agent=USER_AGENT)
                result = fetcher.get(source["url"])
                data, content_type, url, retrieved = (
                    result["bytes"], result["content_type"], result["final_url"], result["retrieved_at"])
            fmt = source["extension"]
            path, meta, created = store.put(data, fmt, retrieved_at=retrieved, provenance=provenance)
            sha = meta["sha256"]
            delivery_id = team + "-" + sha[:24] + "-" + source["adapter_version"]
            if history_root:
                legacy = Path(history_root).expanduser().resolve() / "deliveries" / delivery_id
                if legacy.exists():
                    from fetch.contract.envelope import validate
                    report = validate(legacy)
                    if not report["offline_valid"] or report["provider_id"] != team:
                        raise ValueError("legacy identity mismatch; preserve and investigate")
                    store.record({"started_at": started, "finished_at": now(), "provider_id": team,
                                  "source_id": source["id"], "mode": "reuse" if local else "live",
                                  "outcome": "success", "delivery_id": delivery_id,
                                  "package_replayed": True, "legacy_reused": True,
                                  "collector_revision": revision, "sha256": sha,
                                  "retrieved_at": retrieved})
                    return {"package": str(legacy), "replayed": True, "legacy_reused": True,
                            "acquisition_sha256": sha, **report}
            adapter = adapter_for(team, source.get("adapter"))
            rows = _extract(adapter, data, source, path, retrieved)
            if not rows:
                raise FlowError("registered_field_not_found", "source_schema")
            item_id = source["id"] + ":" + sha[:24]
            for row in rows:
                row["source_item_id"] = item_id
                row.setdefault("revision_of", None)
                row.setdefault("conflicts_with", [])
                row.setdefault("target_ids", [])
                identity = json.dumps({"sha": sha, "adapter": source["adapter_version"], "row": row},
                                      sort_keys=True)
                row["observation_id"] = source["id"] + ":" + digest(identity.encode())[:32]
            item = {
                "source_item_id": item_id,
                "source": {
                    "url": url,
                    "publisher": source["publisher"],
                    "language": source.get("language", "en_or_unmarked"),
                    "categories": source.get("categories") or [],
                    "native_id": source["native_id"],
                },
                "retrieved_at": meta["retrieved_at"],
                "sha256": sha,
                "bytes": len(data),
                "content_type": content_type,
                "format": fmt,
                "access_scope": {"state": "public"},
                "completeness": {"state": "complete", "basis": "SHA verified local source snapshot"},
                "version_relation": {"type": "original"},
                "title": source["title"],
            }
            if meta["retrieved_at"] is None:
                item["reused_at"] = started
                item["provenance_id"] = provenance
            result = build(team, [item], store.root, delivery_id=delivery_id, revision=revision,
                           observations=rows, already_locked=True)
            store.record({"started_at": started, "finished_at": now(), "provider_id": team,
                          "source_id": source["id"], "mode": "reuse" if local else "live",
                          "outcome": "success", "delivery_id": result["delivery_id"],
                          "package_replayed": result["replayed"], "collector_revision": revision,
                          "sha256": sha, "retrieved_at": retrieved, "new_original": created})
            return {**result, "acquisition_sha256": sha, "acquisition_retrieved_at": retrieved}
        except Exception as error:
            store.record_failure(team, source["id"], error, started_at=started,
                                 mode="reuse" if local else "live")
            raise
