"""Server-side logical clock, ISO-8601 helpers and rounding helpers (PRD §2.4, §2.6)."""

import calendar
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# Before any clock call the logical clock reads exactly 2026-08-01T00:00:00Z and
# never falls back to real wall-clock time.
DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def reset():
    _state["now"] = DEFAULT_NOW


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_str():
    return fmt(now())


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a plain YYYY-MM-DD string. Returns a date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(value):
    return value.strftime("%Y-%m-%d")


def add_days_to_date_string(date_string, days):
    return fmt_date(parse_date(date_string) + timedelta(days=int(days)))


def minus_months(instant, months):
    """Subtract whole calendar months from an aware datetime (day clamped)."""
    total = instant.year * 12 + (instant.month - 1) - months
    year = total // 12
    month = total % 12 + 1
    day = min(instant.day, calendar.monthrange(year, month)[1])
    return instant.replace(year=year, month=month, day=day)


def plus_days(instant, days):
    return instant + timedelta(days=days)


def dec(value):
    """Decimal from any numeric input without float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def num(value):
    """Render a Decimal as a JSON number without trailing-zero noise."""
    if isinstance(value, Decimal):
        normalised = value.normalize()
        if normalised == normalised.to_integral_value():
            try:
                return int(normalised)
            except (ValueError, OverflowError):
                return float(normalised)
        return float(value)
    return value


__all__ = [
    "DEFAULT_NOW", "reset", "now", "set_now", "fmt", "now_str", "parse_instant",
    "parse_date", "fmt_date", "add_days_to_date_string", "minus_months", "plus_days",
    "dec", "round_half_up", "ceil_int", "num", "date", "timedelta", "timezone",
]
