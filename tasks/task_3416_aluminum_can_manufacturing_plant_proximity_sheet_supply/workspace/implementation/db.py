"""In-memory data store, logical clock, and id/timestamp helpers.

Storage is in-memory only (dicts keyed by id); every start.sh relaunch is a
fresh boot with an empty store. The logical clock starts at exactly
2026-09-01T00:00:00Z and moves only via the PlatformAdmin clock-set endpoint.
"""
import threading
import time
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

store = {
    "plants": {},
    "customers": {},
    "agreements": {},
    "indices": {},
    "lines": {},
    "formats": {},
    "runs": {},
    "forecasts": {},
    "scrap_returns": {},
    "incidents": {},
}

_lock = threading.Lock()
_seq = [0]
_last_ns = [0]


def parse_ts(value):
    """Parse an ISO-8601 timestamp into an aware datetime (naive -> UTC)."""
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_ns(ns):
    sec, rem = divmod(ns, 1_000_000_000)
    ms = rem // 1_000_000
    base = datetime.fromtimestamp(sec, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, ms)


def now_iso():
    """Strictly increasing wall-clock ISO-8601 UTC timestamp, 3 fractional digits."""
    with _lock:
        ns = time.time_ns()
        if ns <= _last_ns[0]:
            ns = _last_ns[0] + 1_000_000
        _last_ns[0] = ns
        return _fmt_ns(ns)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    with _lock:
        _seq[0] += 1
        return _seq[0]


def touch(entity):
    """Bump updated_at and version on every mutation (PRD section 2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


_clock = {"raw": DEFAULT_CLOCK_UTC, "dt": parse_ts(DEFAULT_CLOCK_UTC)}


def clock_raw():
    return _clock["raw"]


def clock_dt():
    return _clock["dt"]


def clock_date_str():
    return _clock["dt"].strftime("%Y-%m-%d")


def clock_year():
    return _clock["dt"].year


def set_clock(raw):
    _clock["raw"] = raw
    _clock["dt"] = parse_ts(raw)
