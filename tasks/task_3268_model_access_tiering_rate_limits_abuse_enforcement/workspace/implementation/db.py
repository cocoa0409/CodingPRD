"""In-memory data store and logical clock.

Store starts empty on every boot — no seeding of any entity.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

_lock = threading.RLock()

organizations: dict[str, dict] = {}
payment_events: dict[str, dict] = {}
usage_records: dict[str, dict] = {}
model_versions: dict[str, dict] = {}
safety_evaluations: dict[str, dict] = {}
enterprise_agreements: dict[str, dict] = {}
rate_limit_windows: dict[str, dict] = {}  # key: id
queued_requests: dict[str, dict] = {}
invoices: dict[str, dict] = {}
invoice_lines: dict[str, dict] = {}
abuse_cases: dict[str, dict] = {}
abuse_actions: dict[str, dict] = {}
appeals: dict[str, dict] = {}

# RateLimitWindow lookup index: (org_id, model_version_id, window_start_iso) -> window id
window_index: dict[tuple, str] = {}


def parse_iso(s: str) -> datetime:
    """Parse an ISO8601 string (with Z or offset) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_clock(dt: datetime) -> str:
    """Format an aware datetime as ISO8601 UTC (second precision, Z suffix)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


_current_utc: datetime = parse_iso(DEFAULT_CLOCK_ISO)


def now() -> datetime:
    with _lock:
        return _current_utc


def set_now(dt: datetime) -> None:
    global _current_utc
    with _lock:
        _current_utc = dt


def lock() -> threading.RLock:
    return _lock
