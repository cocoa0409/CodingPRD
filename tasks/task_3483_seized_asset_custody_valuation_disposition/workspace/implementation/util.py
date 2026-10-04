"""Shared helpers: timestamps, rounding, request-body and pagination parsing."""

from datetime import datetime, timezone

from flask import request

import errors


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def wall_now():
    """Wall-clock UTC instant for created_at/updated_at/request timestamps.

    PRD §2.4 pins the logical clock only for the enumerated time-relative
    *rules* (incurred_on default, dispute window, months-held, accrual month,
    slot-in-past); the scaffold guarantees created_at tie-breaks are
    impossible because it is server-stamped, which requires a real clock.
    """
    return datetime.now(timezone.utc)


def fmt_dt(value):
    """Serialize a datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def fmt_dt_echo(value):
    """Serialize a domain datetime as ISO 8601 UTC, eliding a zero fraction.

    Domain timestamps (seized_on, appraised_at, forfeited_at, returned_at,
    window/slot bounds, incurred_on) echo the exact instant the client
    supplied or the logical clock reads: PRD §2.4 states the clock reads
    exactly "2026-09-01T00:00:00Z" and §3 stamps "the current logical clock
    time", neither carrying the three-fractional-digit clause that §2.2/§2.5
    pin on api_request_timestamp and created_at/updated_at only.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond == 0:
        return base + "Z"
    return "%s.%03dZ" % (base, value.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime.

    Returns None when the value is not a string or not parseable.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding (SCAFFOLD §1.3): RHU(n, d) = floor((n + floor(d/2)) / d)
# ---------------------------------------------------------------------------
def rhu(n, d=10000):
    """Round-half-up on integers via the pinned floor formula."""
    return (n + d // 2) // d


# ---------------------------------------------------------------------------
# Request body + field validation (validation pipeline tier 3)
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON request body as a dict; {} when absent.

    A non-object JSON body is a malformed request (ERR_INVALID_REQUEST).
    """
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, nonempty=False):
    if not _present(data, name):
        raise errors.invalid_request("Missing required field: %s" % name)
    value = data[name]
    if not isinstance(value, str):
        raise errors.invalid_request("Field %s must be a string" % name)
    if nonempty and value == "":
        raise errors.invalid_request("Field %s must be a non-empty string" % name)
    return value


def req_enum(data, name, domain):
    if not _present(data, name):
        raise errors.invalid_request("Missing required field: %s" % name)
    value = data[name]
    if not isinstance(value, str) or value not in domain:
        raise errors.invalid_request("Field %s must be one of %s" % (name, ", ".join(domain)))
    return value


def req_int(data, name, min_value=None):
    if not _present(data, name):
        raise errors.invalid_request("Missing required field: %s" % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("Field %s must be an integer" % name)
    if min_value is not None and value < min_value:
        raise errors.invalid_request("Field %s must be >= %d" % (name, min_value))
    return value


def opt_int(data, name, min_value=None):
    """Integer-or-absent; returns None when the field is absent/null."""
    if not _present(data, name):
        return None
    return req_int(data, name, min_value=min_value)


def req_dt(data, name):
    if not _present(data, name):
        raise errors.invalid_request("Missing required field: %s" % name)
    parsed = parse_dt(data[name])
    if parsed is None:
        raise errors.invalid_request("Field %s must be an ISO 8601 datetime" % name)
    return parsed


def opt_dt(data, name):
    """Datetime-or-absent; returns None when the field is absent/null."""
    if not _present(data, name):
        return None
    return req_dt(data, name)


def absent_or_none(data, name):
    """True when the field is absent or explicitly null (used for 'forbids')."""
    return not _present(data, name)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, bounds [1, 100]; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("Query parameter limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("Query parameter offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("Query parameter offset must be >= 0")
    return limit, offset


def sort_and_page(items, limit, offset):
    """Sort by created_at ascending (insertion order as tiebreak) and page."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total
