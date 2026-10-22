"""Machine-readable failure classes for logs and retry decisions. Never records arbitrary exception text."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import errno
import socket
import sqlite3
import ssl
from urllib.error import HTTPError, URLError

TRANSIENT_HTTP = (429, 500, 502, 503, 504)
RETRYABLE = {"busy", "delivery_transient", "ack_unknown", "source_transient"}


class FlowError(ValueError):
    """A named, expected failure. `category` decides retry; `code` is the log string."""

    def __init__(self, code, category="integrity_conflict"):
        super().__init__(code)
        self.code, self.category = code, category


def retry_after(headers, at=None):
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        if value.isdigit():
            return int(value)
        instant = parsedate_to_datetime(value)
        if instant.tzinfo is None:
            return None
        return max(0, int((instant - (at or datetime.now(timezone.utc))).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return None


def classify(error, stage):
    """stage: 'acquisition' | 'delivery' | 'configuration'."""
    result = dict(stage=stage, error_type=type(error).__name__, retryable=False,
                  category="unexpected", next_action="inspect; retain originals and history")
    if isinstance(error, FlowError):
        result.update(category=error.category, code=error.code)
        result["retryable"] = error.category in RETRYABLE
    elif isinstance(error, HTTPError):
        result["http_status"] = error.code
        if error.code in TRANSIENT_HTTP:
            result.update(category="source_transient", retryable=True, retry_after_seconds=retry_after(error.headers))
        elif error.code in (401, 403):
            result["category"] = "access_required"
        elif error.code in (404, 410):
            result["category"] = "source_unavailable"
        else:
            result["category"] = "source_http_error"
    elif isinstance(error, ssl.SSLError) or (isinstance(error, URLError) and isinstance(error.reason, ssl.SSLError)):
        result["category"] = "transport_security"
    elif isinstance(error, (TimeoutError, socket.timeout, ConnectionError, URLError)):
        result.update(category="ack_unknown" if stage == "delivery" else "source_transient", retryable=True)
    elif isinstance(error, sqlite3.Error):
        busy = getattr(error, "sqlite_errorname", "") in ("SQLITE_BUSY", "SQLITE_LOCKED")
        result.update(category="busy" if busy else "local_storage", retryable=busy)
    elif isinstance(error, OSError):
        result["errno"] = error.errno
        if error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            result.update(category="busy", retryable=True)
        else:
            result["category"] = "local_storage"
    elif isinstance(error, ValueError):
        result["category"] = "source_schema" if stage == "acquisition" else "configuration"
    elif isinstance(error, (KeyError, TypeError)):
        result["category"] = "configuration"
    if result["retryable"]:
        result["next_action"] = "defer within bounded budget; a delivery retry reuses the frozen package"
    return result
