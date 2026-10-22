"""Adapter base. Subclasses only extract; download, hash, and packaging stay in core/contract."""
from fetch.core.failures import FlowError


class Adapter:
    """Return a list of observation dicts (may be empty) from already-stored original bytes."""

    team = None
    adapter_id = "default"

    def extract(self, data, source, original_path, retrieved_at):
        raise NotImplementedError

    def require(self, condition, code="registered_field_not_found"):
        if not condition:
            raise FlowError(code, "source_schema")
