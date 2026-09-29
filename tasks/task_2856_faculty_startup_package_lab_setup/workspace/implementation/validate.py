"""Payload shape validation (PRD 2.13 priority 3) and calendar parsing (PRD 2.5).

Everything in this module raises ERR_VALIDATION (HTTP 400); nothing here knows
about existence, state or the ledger.
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import envelope
from errors import fail
from money import dec

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)


def body():
    """Parsed JSON object body; an absent body reads as {}."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_VALIDATION", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return parsed


def require(payload, field):
    if field not in payload or payload[field] is None:
        fail("ERR_VALIDATION", "field '%s' is required" % field)
    return payload[field]


def forbid(payload, field, reason):
    if payload.get(field) is not None:
        fail("ERR_VALIDATION", reason)
    return None


def string(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return None
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_VALIDATION", "field '%s' must be a non-empty string" % field)
    return value


def enum(payload, field, members, required=True):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return None
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        fail(
            "ERR_VALIDATION",
            "field '%s' must be one of %s" % (field, ", ".join(sorted(members))),
        )
    return value


def boolean(payload, field, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "field '%s' must be a boolean" % field)
    return value


def _as_int(value, field):
    if isinstance(value, bool):
        fail("ERR_VALIDATION", "field '%s' must be an integer" % field)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 10)
        except ValueError:
            fail("ERR_VALIDATION", "field '%s' must be an integer" % field)
    fail("ERR_VALIDATION", "field '%s' must be an integer" % field)


def integer(payload, field, required=True, minimum=None, maximum=None, exclusive_min=None):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return None
    value = _as_int(payload[field], field)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "field '%s' must be at least %d" % (field, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        fail(
            "ERR_VALIDATION",
            "field '%s' must be greater than %d" % (field, exclusive_min),
        )
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "field '%s' must be at most %d" % (field, maximum))
    return value


def cents(payload, field, required=True, positive=False):
    """An integer number of cents; at least 0, or strictly positive."""
    if positive:
        return integer(payload, field, required=required, exclusive_min=0)
    return integer(payload, field, required=required, minimum=0)


def percent(payload, field, required=True, minimum=0, maximum=100):
    return integer(payload, field, required=required, minimum=minimum, maximum=maximum)


def number(payload, field, required=True, minimum=None, exclusive_min=None, maximum=None):
    """A Decimal-backed number (power in kW, fte)."""
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        fail("ERR_VALIDATION", "field '%s' must be a number" % field)
    try:
        parsed = dec(value)
    except (InvalidOperation, ValueError, ArithmeticError):
        fail("ERR_VALIDATION", "field '%s' must be a number" % field)
    if not parsed.is_finite():
        fail("ERR_VALIDATION", "field '%s' must be a finite number" % field)
    if minimum is not None and parsed < dec(minimum):
        fail("ERR_VALIDATION", "field '%s' must be at least %s" % (field, minimum))
    if exclusive_min is not None and parsed <= dec(exclusive_min):
        fail("ERR_VALIDATION", "field '%s' must be greater than %s" % (field, exclusive_min))
    if maximum is not None and parsed > dec(maximum):
        fail("ERR_VALIDATION", "field '%s' must be at most %s" % (field, maximum))
    return parsed


# ---------------------------------------------------------------------------
# Calendar parsing (PRD 2.5): date fields are YYYY-MM-DD, instant fields are
# full ISO 8601 UTC timestamps.
# ---------------------------------------------------------------------------


def parse_instant(text, field):
    if not isinstance(text, str) or not _INSTANT_RE.match(text):
        fail("ERR_VALIDATION", "field '%s' must be an ISO 8601 UTC instant" % field)
    normalized = text.strip()
    if normalized[-1] in ("Z", "z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        fail("ERR_VALIDATION", "field '%s' must be an ISO 8601 UTC instant" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instant(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return None
    return parse_instant(payload[field], field)


def parse_date(text, field):
    if not isinstance(text, str) or not _DATE_RE.match(text):
        fail("ERR_VALIDATION", "field '%s' must be a YYYY-MM-DD calendar date" % field)
    try:
        return date.fromisoformat(text)
    except ValueError:
        fail("ERR_VALIDATION", "field '%s' must be a YYYY-MM-DD calendar date" % field)


def calendar_date(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return None
    return parse_date(payload[field], field)


def identifier(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            fail("ERR_VALIDATION", "field '%s' is required" % field)
        return None
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_VALIDATION", "field '%s' must be an identifier string" % field)
    return value


def date_at_or_before(earlier, later, message):
    if earlier is not None and later is not None and earlier > later:
        fail("ERR_VALIDATION", message)


def strictly_before(earlier, later, message):
    if earlier is not None and later is not None and earlier >= later:
        fail("ERR_VALIDATION", message)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = envelope.PAGINATION_DEFAULT_LIMIT
    offset = envelope.PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit, 10)
        except ValueError:
            fail("ERR_VALIDATION", "limit must be an integer")
        if limit < envelope.PAGINATION_MIN_LIMIT or limit > envelope.PAGINATION_MAX_LIMIT:
            fail(
                "ERR_VALIDATION",
                "limit must be between %d and %d"
                % (envelope.PAGINATION_MIN_LIMIT, envelope.PAGINATION_MAX_LIMIT),
            )
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset, 10)
        except ValueError:
            fail("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be at least 0")
    return limit, offset


def filter_value(name, members=None):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if members is not None and value not in members:
        fail("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(sorted(members))))
    return value


def filter_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value, 10)
    except ValueError:
        fail("ERR_VALIDATION", "%s must be an integer" % name)


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
