"""Polite fetcher with an immutable raw archive.

    from sourcebound.fetch import Fetcher
    f = Fetcher("ecb_data_portal")
    resp, ref = f.get("https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A",
                      params={"format": "csvdata", "startPeriod": "2026-01-01"})
    rows = parse(resp.content)            # parsers also run later on f.read(ref.sha256)

Rules (enforced, not optional):
  * one request per host every min_interval + U(0, jitter) seconds; honest User-Agent;
    robots.txt respected; conditional requests (ETag / Last-Modified)
  * 401/403/407/429/451, 503 and CAPTCHA/challenge pages STOP that host for this source:
    a BLOCKED.<host> marker is written and every later request to the host raises Blocked
    until a human clears it (`sb unblock <source> [host]`). No proxies, no CAPTCHA solving, no fingerprint tricks.
  * credentials: only a token the provider issued for this access, named in the source's
    register entry as `auth: {env: VARIABLE, header: Authorization, prefix: "Bearer "}` and
    read from the environment; it is sent as a header and never written to the archive.
    No website logins, no shared or borrowed accounts.
  * every response body is stored unchanged (zstd) under <raw>/<source>/YYYY/MM/DD/,
    content-addressed by sha256, with one manifest line per request. Staged tables carry
    raw_ref = sha256, so each row can be traced to the exact bytes it was parsed from.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import zstandard

from . import config

STOP_STATUS = {401, 403, 407, 429, 451, 503}
RETRY_STATUS = {500, 502, 504}
CHALLENGE_MARKERS = (b"cf-challenge", b"challenge-platform", b"are you a robot", b"unusual traffic")
SHORT_PAGE_MARKERS = (b"captcha", b"access denied")     # only on short pages: long ones merely mention them
SHORT_PAGE = 15_000


def _challenge(body: bytes) -> bool:
    head = body[:20000].lower()
    return any(m in head for m in CHALLENGE_MARKERS) or (
        len(body) < SHORT_PAGE and any(m in head for m in SHORT_PAGE_MARKERS))

EXT = {"text/html": "html", "application/json": "json", "text/csv": "csv", "application/xml": "xml",
       "text/xml": "xml", "application/pdf": "pdf", "application/vnd.sdmx.data+csv": "csv",
       "text/plain": "txt", "application/vnd.apache.parquet": "parquet", "application/zip": "zip",
       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
       "application/vnd.ms-excel": "xls"}

_robots: dict[str, RobotFileParser] = {}


def _marker(host: str) -> str:
    """Host as a file name (a port's colon is not allowed in Windows file names)."""
    return host.replace(":", "_")


class Blocked(RuntimeError):
    """The source signalled that we should stop. Do not retry automatically."""


@dataclass(frozen=True)
class RawRef:
    source: str
    sha256: str
    path: str               # relative to the raw root
    url: str
    status: int
    fetched_at: str
    content_type: str


class Fetcher:
    def __init__(self, source: str, *, min_interval: float | None = None, jitter: float | None = None,
                 respect_robots: bool | None = None, timeout: float = 30.0, headers: dict | None = None):
        if not source.replace("_", "").isalnum():
            raise ValueError("source id: letters, digits and _ only")
        self.h = config.hub()
        self.source = source
        self.dir = self.h.raw_root / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = self.h.min_interval if min_interval is None else min_interval
        self.jitter = self.h.jitter if jitter is None else jitter
        self.respect_robots = self.h.respect_robots if respect_robots is None else respect_robots
        self.client = httpx.Client(timeout=timeout, follow_redirects=True,
                                   headers={"User-Agent": self.h.user_agent, **(headers or {})})
        self._token, self._token_hosts = self._auth()
        self._cache_file = self.dir / "http_cache.json"
        self._cache = json.loads(self._cache_file.read_text(encoding="utf-8")) if self._cache_file.exists() else {}

    def _auth(self) -> tuple[dict, set[str]]:
        """(header with the token named in the register entry, hosts it may be sent to).

        The token goes only to the host of the entry's `url:` and to those under `auth: hosts:`,
        never to another site (documentation pages, redirect targets, robots.txt requests).
        """
        import os

        import yaml
        f = self.h.datasource(self.source)
        entry = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f else {}
        auth = entry.get("auth")
        if not isinstance(auth, dict) or not auth.get("env"):
            return {}, set()
        token = os.environ.get(auth["env"])
        if not token:
            raise RuntimeError(f"datasource {self.source}: set the environment variable {auth['env']} (access token)")
        hosts = {urlsplit(str(entry.get("url") or "")).netloc, *map(str, auth.get("hosts") or [])} - {""}
        if not hosts:
            raise RuntimeError(f"datasource {self.source}: the register entry needs `url:` (the token is sent to that host only)")
        return {auth.get("header", "Authorization"): f"{auth.get('prefix', 'Bearer ')}{token}"}, hosts

    def _headers(self, url: str) -> dict:
        return self._token if urlsplit(url).netloc in self._token_hosts else {}

    # ------------------------------------------------------------------ guards
    def blocked_file(self, url: str) -> Path:
        """Stop marker per host: one refusing site never silences the others."""
        return self.dir / f"BLOCKED.{_marker(urlsplit(url).netloc)}"

    def _guard(self, url: str) -> None:
        f = self.blocked_file(url)
        if f.exists():
            self._log(url, "refused:stopped", None)
            raise Blocked(f"{self.source} is blocked for {urlsplit(url).netloc}: {f.read_text(encoding='utf-8').strip()} "
                          f"-- check manually, then `sb unblock {self.source} {urlsplit(url).netloc}`")
        if self.respect_robots and not self._robots_ok(url):
            self._log(url, "refused:robots", None)
            raise Blocked(f"robots.txt disallows {url} for our user agent")

    def _robots_ok(self, url: str) -> bool:
        """Whether robots.txt of the host lets our user agent fetch `url`.

        A robots.txt that exists is followed.  One that is missing (404 and other 4xx) allows
        everything.  One that is refused (401, 403), fails (5xx) or cannot be reached allows
        nothing: a site that will not show its rules has not invited us.
        """
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in _robots:
            rp = RobotFileParser()
            try:
                self._wait(parts.netloc)            # robots.txt is a request to the host like any other
                r = self.client.get(base + "/robots.txt")
                refused = r.status_code in (401, 403) or r.status_code >= 500
                rp.parse(["User-agent: *", "Disallow: /"] if refused else r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse(["User-agent: *", "Disallow: /"])
            _robots[base] = rp
        return _robots[base].can_fetch(self.h.user_agent, url)

    def _wait(self, host: str) -> None:
        """One request per host every min_interval + jitter seconds, across all processes on this
        machine (parallel agents, repeated `sb snap`): the time of the last request is a file."""
        stamp = self.h.raw_root / ".hosts" / f"{_marker(host)}.last"
        with config.locked(stamp, stale=self.min_interval + self.jitter + 120):
            gap = self.min_interval + random.uniform(0, self.jitter)
            try:
                dt = time.time() - float(stamp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                dt = gap
            if 0 <= dt < gap:
                time.sleep(gap - dt)
            stamp.write_text(repr(time.time()), encoding="utf-8")

    def _block(self, url: str, reason: str) -> None:
        self.blocked_file(url).write_text(f"{datetime.now(timezone.utc).isoformat()} {reason}\n", encoding="utf-8")
        raise Blocked(f"{self.source}: {reason} -- stopped; nothing will be retried")

    # ------------------------------------------------------------------ requests
    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> tuple[httpx.Response, RawRef]:
        full = url + ("?" + urlencode(params, doseq=True) if params else "")
        self._guard(full)
        cached = self._cache.get(full, {})
        cond = {}
        if cached.get("etag"):
            cond["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            cond["If-Modified-Since"] = cached["last_modified"]
        for attempt in range(3):            # transient gateway errors: wait long, retry twice
            try:
                r = self._send(url, params, {**cond, **(headers or {})})
            except httpx.TimeoutException:
                if attempt == 2:
                    raise
                time.sleep(30 * (attempt + 1))
                continue
            if r.status_code not in RETRY_STATUS or attempt == 2:
                break
            time.sleep(30 * (attempt + 1))
        if r.status_code == 304 and cached.get("ref"):
            ref = RawRef(**cached["ref"])
            self._log(full, r.status_code, ref)
            return httpx.Response(200, content=self.read(ref.sha256), request=r.request,
                                  headers={"content-type": ref.content_type}), ref
        final = str(r.url)                          # after redirects: the host that actually answered
        if r.status_code in STOP_STATUS:
            self._log(full, r.status_code, None)
            self._block(final, f"HTTP {r.status_code} from {urlsplit(final).netloc}")
        if r.headers.get("content-type", "").startswith("text/html") and _challenge(r.content):
            self._log(full, r.status_code, None)
            self._block(final, f"challenge/CAPTCHA page from {urlsplit(final).netloc}")
        r.raise_for_status()
        ref = self.store(r.content, url=full, status=r.status_code,
                         content_type=r.headers.get("content-type", "application/octet-stream"))
        self._cache[full] = {"etag": r.headers.get("etag"), "last_modified": r.headers.get("last-modified"),
                             "ref": asdict(ref)}
        config.write_atomic(self._cache_file, json.dumps(self._cache, indent=1))
        return r, ref

    def _send(self, url: str, params: dict | None, headers: dict) -> httpx.Response:
        """One request, following redirects by hand: every hop is paced and checked like a
        request of its own (stop markers, robots.txt), and the token goes only to its hosts."""
        for hop in range(6):
            self._wait(urlsplit(url).netloc)
            r = self.client.get(url, params=params if hop == 0 else None, follow_redirects=False,
                                headers={**headers, **self._headers(url)})
            if not (r.is_redirect and r.headers.get("location")):
                return r
            url = str(r.url.join(r.headers["location"]))
            self._guard(url)
        raise httpx.TooManyRedirects("more than 5 redirects", request=r.request)

    def render(self, url: str, *, wait_for: str | None = None) -> tuple[str, RawRef]:
        """JavaScript-rendered HTML via Playwright (only when no JSON endpoint exists)."""
        from playwright.sync_api import sync_playwright  # optional dependency

        self._guard(url)
        self._wait(urlsplit(url).netloc)
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(user_agent=self.h.user_agent)
            resp = page.goto(url, wait_until="networkidle")
            if resp is not None and resp.status in STOP_STATUS:
                b.close()
                self._block(url, f"HTTP {resp.status} from {urlsplit(url).netloc} (browser)")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=15000)
            html = page.content()
            b.close()
        if _challenge(html.encode()):
            self._block(url, f"challenge/CAPTCHA page from {urlsplit(url).netloc} (browser)")
        ref = self.store(html.encode(), url=url, status=200, content_type="text/html")
        return html, ref

    # ------------------------------------------------------------------ archive
    def store(self, body: bytes, *, url: str, status: int = 200, content_type: str = "",
              meta: dict | None = None) -> RawRef:
        sha = hashlib.sha256(body).hexdigest()
        now = datetime.now(timezone.utc)
        ext = EXT.get(content_type.split(";")[0].strip(), "bin")
        rel = f"{self.source}/{now:%Y/%m/%d}/{sha[:20]}.{ext}.zst"
        existing = list(self.dir.glob(f"*/*/*/{sha[:20]}.*.zst"))
        if existing:
            rel = existing[0].relative_to(self.h.raw_root).as_posix()
        else:
            dest = self.h.raw_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zstandard.ZstdCompressor(level=10).compress(body))
        ref = RawRef(self.source, sha, rel, url, status, now.isoformat(timespec="seconds"), content_type)
        self._log(url, status, ref, meta)
        return ref

    def _log(self, url: str, status: int | str, ref: RawRef | None, meta: dict | None = None) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "url": url,
                "status": status, "sha256": ref.sha256 if ref else None, "path": ref.path if ref else None,
                **(meta or {})}
        with (self.dir / "manifest.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")

    def read(self, sha256: str) -> bytes:
        return read_raw(self.source, sha256)

    def manifest(self) -> list[dict]:
        m = self.dir / "manifest.jsonl"
        return [json.loads(x) for x in m.read_text(encoding="utf-8").splitlines()] if m.exists() else []


def read_raw(source: str, sha256: str) -> bytes:
    """Bytes of an archived response (for re-parsing without re-fetching)."""
    h = config.hub()
    hits = list((h.raw_root / source).glob(f"*/*/*/{sha256[:20]}.*.zst"))
    if not hits:
        raise FileNotFoundError(f"raw {source}/{sha256[:20]} not in archive")
    return zstandard.ZstdDecompressor().decompress(hits[0].read_bytes(), max_output_size=1 << 31)


def unblock(source: str, host: str | None = None) -> list[str]:
    """Remove stop markers of a source (all hosts, or one). Returns the cleared hosts."""
    d = config.hub().raw_root / source
    cleared = []
    for f in d.glob(f"BLOCKED.{_marker(host)}" if host else "BLOCKED*"):
        cleared.append(f.name.removeprefix("BLOCKED.").removeprefix("BLOCKED"))
        f.unlink()
    return cleared


def blocked(source: str) -> dict[str, str]:
    d = config.hub().raw_root / source
    return {f.name.removeprefix("BLOCKED."): f.read_text(encoding="utf-8").strip() for f in d.glob("BLOCKED*")}
