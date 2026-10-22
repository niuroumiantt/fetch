"""Drain website run requests on a collector host. Provides no website crawl.

Polls inresearch `/api/fetch-runs/worker/*` with a Bearer token, claims each
requested source, runs local `collect`, and reports classified outcomes only.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path

from fetch.config import load_sources, select
from fetch.core.failures import classify
from fetch.core.http import now


def _request(base, token, method, path, body=None, timeout=60):
    url = base.rstrip("/") + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "fetch-drain-requests/1",
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode() or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            payload = {"ok": False, "error": "http_%s" % error.code}
        return error.code, payload


def _report_payload(result=None, error=None, mode=None):
    if error is not None:
        failure = classify(error, "acquisition")
        return {
            "outcome": "failed",
            "failure_code": failure.get("code") or failure.get("category") or "collect_failed",
            "mode": mode,
        }
    return {
        "outcome": "success",
        "delivery_id": result.get("delivery_id"),
        "acquisition_sha256": result.get("acquisition_sha256"),
        "package_path": result.get("package"),
        "candidate_rows": result.get("candidate_rows"),
        "unique_originals": result.get("unique_originals"),
        "offline_valid": result.get("offline_valid"),
        "mode": mode or ("reuse" if result.get("replayed") else "live"),
        "retrieved_at": result.get("acquisition_retrieved_at"),
    }


def drain(base_url, token, *, collector_host=None, data_root=None, limit=20,
          respect_robots=True):
    """Claim pending website requests and run local collection. Returns a summary."""
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        # Allow http://127.0.0.1 for local tests only via explicit env.
        if not (isinstance(base_url, str) and base_url.startswith("http://")
                and os.environ.get("FETCH_DRAIN_ALLOW_HTTP") == "1"):
            raise ValueError("base_url_must_be_https_or_test_http")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("collector_token_required")
    host = collector_host or socket.gethostname().split(".")[0][:80]
    status, pending = _request(base_url, token, "GET", "/api/fetch-runs/worker/pending")
    if status != 200:
        raise ValueError("pending_fetch_failed")
    requests = list(pending.get("requests") or [])[: max(0, int(limit))]
    summary = {"at": now(), "collector_host": host, "claimed": 0, "reported": 0, "results": []}
    from fetch.collect import collect
    for row in requests:
        request_id = row.get("id")
        team = row.get("provider_id")
        source_id = row.get("source_id")
        claim_status, claim = _request(
            base_url, token, "POST", "/api/fetch-runs/worker/claim",
            {"request_id": request_id, "collector_host": host})
        if claim_status != 200:
            summary["results"].append({
                "request_id": request_id, "outcome": "claim_skipped",
                "failure_code": (claim.get("error") or "claim_failed")[:80]})
            continue
        summary["claimed"] += 1
        mode = "live"
        try:
            sources = select(load_sources(team), source_id)
            if len(sources) != 1:
                raise ValueError("source_not_registered_locally")
            root = (Path(data_root).expanduser() if data_root
                    else Path.home() / ".local/share/fetch" / team)
            result = collect(sources[0], root, respect_robots=respect_robots)
            report = _report_payload(result=result, mode=mode)
        except Exception as error:
            report = _report_payload(error=error, mode=mode)
        report["request_id"] = request_id
        rep_status, rep = _request(
            base_url, token, "POST", "/api/fetch-runs/worker/report", report)
        summary["reported"] += 1 if rep_status == 200 else 0
        summary["results"].append({
            "request_id": request_id,
            "provider_id": team,
            "source_id": source_id,
            "outcome": report.get("outcome"),
            "failure_code": report.get("failure_code"),
            "delivery_id": report.get("delivery_id"),
            "report_status": rep_status,
            "receive": (rep or {}).get("receive"),
        })
    return summary
