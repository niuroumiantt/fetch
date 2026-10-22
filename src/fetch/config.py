"""Team source registry. One source belongs to one team, one host, one calendar."""
import json

from fetch import ROOT, TEAMS

REQUIRED = ("id", "team", "publisher", "title", "url", "hosts", "native_id",
            "extension", "content_type", "adapter_version", "cadence", "execution_host")
HOSTS = frozenset({"aws", "macmini"})


def load_sources(team):
    if team not in TEAMS:
        raise ValueError("unknown provider")
    path = ROOT / "config" / team / "sources.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict) and "sources" not in value:
        value = {"team": value["team"], "sources": [value]}
    if not isinstance(value, dict) or value.get("team") != team or not isinstance(value.get("sources"), list):
        raise ValueError("config/provider mismatch")
    sources, ids = [], set()
    for source in value["sources"]:
        if not isinstance(source, dict) or source.get("team") != team:
            raise ValueError("config/provider mismatch")
        missing = [key for key in REQUIRED if key not in source]
        if missing:
            raise ValueError("source missing fields: " + ",".join(missing))
        if source["id"] in ids:
            raise ValueError("duplicate registered source id")
        if not isinstance(source["hosts"], list) or not source["hosts"]:
            raise ValueError("hosts required")
        if source["execution_host"] not in HOSTS:
            raise ValueError("execution_host must be aws or macmini")
        if source.get("scheduled", False) not in (True, False):
            raise ValueError("scheduled must be boolean")
        ids.add(source["id"])
        sources.append(source)
    return sources


def select(sources, source_id=None):
    if source_id is None:
        return list(sources)
    chosen = [source for source in sources if source["id"] == source_id]
    if not chosen:
        raise ValueError("registered source id not found for team")
    return chosen


def check_all():
    return {team: {"provider_id": team, "source_ids": [s["id"] for s in load_sources(team)],
                   "scheduled": any(s.get("scheduled") for s in load_sources(team)),
                   "model_required": False} for team in TEAMS}
