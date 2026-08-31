"""Datetime, rounding and numeric helpers.

All exact arithmetic goes through fractions.Fraction so that the pinned
round-half-up orders described in PRD 2.6 are reproduced exactly.
"""
from __future__ import annotations

import datetime as _dt
import random
import string
import uuid
from fractions import Fraction

ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def new_id() -> str:
    return str(uuid.uuid4())


def request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def format_dt(dt: _dt.datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return dt.strftime(ISO_FMT)[:-3] + "Z"


def parse_dt(value):
    """Parse an ISO 8601 instant into a naive UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("not a datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a date string")
    return _dt.datetime.strptime(value.strip(), "%Y-%m-%d").date()


def add_days(dt: _dt.datetime, days: int) -> _dt.datetime:
    return dt + _dt.timedelta(days=days)


def seconds_between(later, earlier) -> int:
    """Whole seconds between two naive UTC datetimes (may be negative)."""
    return int((later - earlier).total_seconds())


# --------------------------------------------------------------------------
# round-half-up primitives (exact, over Fraction)
# --------------------------------------------------------------------------

def _floor_div(num: int, den: int) -> int:
    return num // den


def round_half_up_int(value) -> int:
    """Round an exact rational to the nearest integer, ties away from zero."""
    fr = Fraction(value)
    if fr >= 0:
        n = (fr.numerator * 2 + fr.denominator) // (2 * fr.denominator)
        return n
    fr = -fr
    n = (fr.numerator * 2 + fr.denominator) // (2 * fr.denominator)
    return -n


def round_half_up_places(value, places: int) -> Fraction:
    scale = 10 ** places
    scaled = Fraction(value) * scale
    return Fraction(round_half_up_int(scaled), scale)


def two_dp(value) -> float:
    """Round-half-up to two decimals, returned as a JSON-friendly float."""
    scale = 100
    n = round_half_up_int(Fraction(value) * scale)
    return n / 100.0


def ceil_div(num: int, den: int) -> int:
    return -((-num) // den)
