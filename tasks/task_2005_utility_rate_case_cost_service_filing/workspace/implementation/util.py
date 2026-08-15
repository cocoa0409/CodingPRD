"""Shared helpers: ids, timestamps, logical clock, exact-integer rounding."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Envelope meta timestamp: ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.6): default 2026-08-01T00:00:00Z, strictly forward.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
        from errors import raise_error, ERR_CLOCK_REGRESSION
        new_dt = _parse_dt(to_iso8601)
        if new_dt <= self._dt:
            raise_error(ERR_CLOCK_REGRESSION,
                        "to_iso8601 must be strictly after the current logical clock")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


def parse_datetime(s: str) -> datetime:
    return _parse_dt(s)


def fmt_datetime(dt: datetime) -> str:
    return _fmt_dt(dt)


def plus_days_iso(dt: datetime, days: int) -> str:
    return _fmt_dt(dt + timedelta(days=days))


def round_half_up_signed(numer, denom) -> int:
    """round(numer/denom) to integer, ties away from zero (== half-up for
    non-negative numerators). Exact integer arithmetic. denom > 0."""
    numer = int(numer)
    denom = int(denom)
    if denom <= 0:
        raise ZeroDivisionError("denom must be positive")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


# round half away from zero is the same symmetric rule
round_half_away_from_zero = round_half_up_signed
