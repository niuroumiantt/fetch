"""Bounded HTTPS retrieval. Provides bytes plus retrieval metadata; provides no parsing.

Rules every team inherits: HTTPS only, exact host allowlist (redirects included),
robots.txt per actual host (fail-closed when the policy cannot be read), crawl
delay, 20 MiB per response, three bounded attempts, no credentials in URLs,
declared gzip decoded in bounded memory (transport encoding is not content).
"""
from datetime import datetime, timezone
import gzip
import hashlib
import random
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import zlib

from fetch import USER_AGENT
from fetch.core.failures import FlowError, TRANSIENT_HTTP, classify, retry_after
from fetch.core.robots import Robots

MAX_BYTES = 20 * 1024 * 1024
ROBOTS_BYTES = 1024 * 1024
GZIP_MAGIC = b"\x1f\x8b"
MAX_RETRY_AFTER = 5


def now():
    return datetime.now(timezone.utc).isoformat()


def check_url(url, hosts):
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.hostname not in hosts
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise FlowError("url_outside_registered_https_hosts", "configuration")
    return parts


def decode_body(encoding, data, limit):
    if "gzip" not in (encoding or "").lower():
        return data
    if not data.startswith(GZIP_MAGIC):
        raise FlowError("declared_gzip_without_magic", "source_schema")
    try:
        body = gzip.decompress(data)
    except (OSError, EOFError, zlib.error) as error:
        raise FlowError("declared_gzip_incomplete", "source_schema") from error
    if len(body) > limit:
        raise FlowError("decoded_source_exceeds_budget", "source_schema")
    return body


class _Redirects(HTTPRedirectHandler):
    def __init__(self, check):
        self.check = check

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    """One instance per run and host family. Not thread-safe by design: one writer per team."""

    def __init__(self, hosts, *, delay_seconds=1.0, timeout=30, max_bytes=MAX_BYTES, user_agent=USER_AGENT,
                 respect_robots=True, opener=None, sleep=time.sleep, clock=time.monotonic):
        self.hosts = frozenset(hosts)
        self.delay, self.timeout, self.max_bytes, self.user_agent = delay_seconds, timeout, max_bytes, user_agent
        self.respect_robots = respect_robots
        self._sleep, self._clock, self._last = sleep, clock, None
        self._robots, self._policy_failures, self.policy_receipts = {}, {}, []
        self._loading_robots = False
        self.opener = opener or build_opener(_Redirects(self._check), HTTPSHandler(context=ssl.create_default_context()))

    # policy -----------------------------------------------------------------
    def _check(self, url):
        parts = check_url(url, self.hosts)
        if not self.respect_robots or self._loading_robots:
            if self._loading_robots and (parts.path != "/robots.txt" or parts.query):
                raise FlowError("robots_redirect_left_policy_path", "configuration")
            return
        if parts.path == "/robots.txt" and not parts.query:
            return
        policy = self._policy(parts.hostname)
        if not policy.allowed(url):
            raise FlowError("robots_disallowed", "access_required")

    def _policy(self, host):
        if host in self._robots:
            return self._robots[host]
        if host in self._policy_failures:
            raise FlowError("robots_unavailable", "source_transient")
        url = "https://" + host + "/robots.txt"
        self._loading_robots = True
        try:
            try:
                data, meta = self._request(url, limit=ROBOTS_BYTES)
                text, status = data.decode("utf-8", "replace"), meta["status"]
            except HTTPError as error:
                if error.code not in (404, 410):
                    raise
                text, status = "", error.code
            self._robots[host] = Robots(text, self.user_agent)
            self.policy_receipts.append({"url": url, "observed_at": now(), "status": status,
                                         "sha256": hashlib.sha256(text.encode()).hexdigest()})
            return self._robots[host]
        except Exception as error:
            self._policy_failures[host] = classify(error, "acquisition")
            self.policy_receipts.append({"url": url, "observed_at": now(), "status": "blocked",
                                         "failure": self._policy_failures[host]})
            raise FlowError("robots_unavailable", "source_transient") from error
        finally:
            self._loading_robots = False

    def _pace(self, host):
        policy = self._robots.get(host)
        delay = max(self.delay, (policy.delay or 0) if policy else 0)
        if self._last is not None:
            self._sleep(max(0.0, self._last + delay - self._clock()))
        self._last = self._clock()

    # transport ---------------------------------------------------------------
    def _request(self, url, *, limit, conditional=None):
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "identity"}
        if conditional:
            if conditional.get("etag"):
                headers["If-None-Match"] = conditional["etag"]
            if conditional.get("last_modified"):
                headers["If-Modified-Since"] = conditional["last_modified"]
        self._pace(urlsplit(url).hostname)
        with self.opener.open(Request(url, headers=headers), timeout=self.timeout) as response:
            check_url(response.url, self.hosts)
            data = response.read(limit + 1)
            if len(data) > limit:
                raise FlowError("source_exceeds_budget", "source_schema")
            data = decode_body(response.headers.get("Content-Encoding"), data, limit)
            meta = {"final_url": response.url, "status": response.status,
                    "content_type": response.headers.get_content_type(),
                    "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
            return data, meta

    def get(self, url, *, conditional=None):
        """Return {bytes, sha256, retrieved_at, final_url, status, content_type, etag, last_modified}.

        Returns None on 304 when `conditional` carried a validator; an empty 200 body is an error.
        """
        self._check(url)
        for attempt in range(3):
            try:
                data, meta = self._request(url, limit=self.max_bytes, conditional=conditional)
                if not data:
                    raise FlowError("empty_source", "source_schema")
                return {"bytes": data, "sha256": hashlib.sha256(data).hexdigest(), "retrieved_at": now(), **meta}
            except HTTPError as error:
                if error.code == 304 and conditional:
                    return None
                if error.code not in TRANSIENT_HTTP or attempt == 2:
                    raise
                wait = retry_after(error.headers)
                if wait is not None:
                    if wait > MAX_RETRY_AFTER:
                        raise  # persist the deferral; never block a run on a long Retry-After
                    self._sleep(wait)
                    continue
            except (URLError, TimeoutError, ConnectionError) as error:
                if attempt == 2 or not classify(error, "acquisition")["retryable"]:
                    raise
            self._sleep(2 ** attempt + random.uniform(0, 0.25))
        raise FlowError("retry_budget_exhausted", "source_transient")
