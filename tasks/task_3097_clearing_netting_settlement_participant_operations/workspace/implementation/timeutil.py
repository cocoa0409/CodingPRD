"""Datetime helpers.

Deadlines are compared as instants. Where PRD names a string comparison the
result is identical for well-formed inputs; parsing only makes the comparison
tolerant of differing fractional-second spellings.
"""

from datetime import date, datetime, timedelta, timezone

from errors import api_error, ERR_INVALID_REQUEST


def parse_iso(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_iso_instant(value):
    return parse_iso(value) is not None


def normalize_iso(value):
    """Canonical ISO 8601 UTC with three fractional digits."""
    parsed = parse_iso(value)
    if parsed is None:
        return value
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (parsed.microsecond // 1000)


def instant_lt(left, right):
    """True when left is strictly before right."""
    first, second = parse_iso(left), parse_iso(right)
    if first is None or second is None:
        return str(left) < str(right)
    return first < second


def instant_ge(left, right):
    first, second = parse_iso(left), parse_iso(right)
    if first is None or second is None:
        return str(left) >= str(right)
    return first >= second


def instant_le(left, right):
    first, second = parse_iso(left), parse_iso(right)
    if first is None or second is None:
        return str(left) <= str(right)
    return first <= second


def date_part(value):
    """The YYYY-MM-DD date portion of an ISO instant or date string."""
    if not isinstance(value, str):
        return None
    return value.strip()[:10]


# Standard rolling settlement cycle: a trade settles two calendar days after
# its trade_date, so a trade executed on 2026-09-08 carries settlement_date
# 2026-09-10. The window's own trade_entry_deadline and affirmation_deadline
# are what pin the cycle's cut-offs; this derivation only fixes which window a
# trade is designated against.
SETTLEMENT_LAG_DAYS = 2


def settlement_date_for(trade_date):
    """The settlement date a trade is designated against: trade_date + T+2."""
    parsed = parse_iso(trade_date)
    if parsed is None:
        return None
    return (parsed.date() + timedelta(days=SETTLEMENT_LAG_DAYS)).isoformat()


def is_iso_date(value):
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) != 10:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def require_instant(value, field_name):
    if not is_iso_instant(value):
        raise api_error(ERR_INVALID_REQUEST, "%s must be an ISO 8601 UTC instant." % field_name)
    return value


def require_date(value, field_name):
    if not is_iso_date(value):
        raise api_error(ERR_INVALID_REQUEST, "%s must be an ISO 8601 date of the form YYYY-MM-DD." % field_name)
    return value