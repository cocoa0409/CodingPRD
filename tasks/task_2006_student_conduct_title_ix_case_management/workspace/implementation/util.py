"""Shared helpers: ids, request ids, timestamps, logical clock, calendar math."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

SECONDS_PER_DAY = 86400


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC wall-clock timestamp with three fractional digits.

    Used for envelope meta.api_request_timestamp and resource created_at/
    updated_at bookkeeping fields (PRD 2.4 mandates three fractional digits).
    Business timestamps read the logical clock instead.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): startup default exactly 2026-08-01T00:00:00Z, never
# falls back to wall clock. All "now" semantics read this clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Timestamp comparisons at second precision (PRD calc precision notes).
    return dt.replace(microsecond=0)


def _fmt_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = _parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        self._dt = _parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


def clock_iso() -> str:
    return CLOCK.now_iso()


def clock_dt() -> datetime:
    return CLOCK.now()


def add_days_iso(dt: datetime, days: int) -> str:
    return _fmt_dt(dt + timedelta(days=days))


def add_years(dt: datetime, years: int) -> datetime:
    """Calendrical year addition for the retention boundary (Feb 29 clamps)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


# Monotonic insertion sequence for deterministic ordering ties.
_SEQ = {"n": 0}


def next_seq() -> int:
    _SEQ["n"] += 1
    return _SEQ["n"]
