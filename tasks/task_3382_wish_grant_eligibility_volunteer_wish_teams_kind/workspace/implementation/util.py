"""Parsing, validation, date/age math, rounding, and pagination helpers."""

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def body_json(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            bad("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def req_field(body, name):
    v = body.get(name, None)
    if v is None:
        bad("Missing required field: %s" % name)
    return v


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        bad("Field %s must be a string" % name)
    return v


def opt_str(body, name):
    v = body.get(name, None)
    if v is None:
        return None
    if not isinstance(v, str):
        bad("Field %s must be a string" % name)
    return v


def req_int(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %s must be an integer" % name)
    return v


def opt_int(body, name):
    v = body.get(name, None)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %s must be an integer" % name)
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        bad("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def parse_date(v, field):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        bad("Field %s must be a YYYY-MM-DD date" % field)
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        bad("Field %s must be a valid YYYY-MM-DD date" % field)


def req_date(body, name):
    return parse_date(req_field(body, name), name)


def parse_datetime(v, field):
    if not isinstance(v, str):
        bad("Field %s must be an ISO 8601 datetime" % field)
    t = v.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        bad("Field %s must be a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, name):
    return parse_datetime(req_field(body, name), name)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def age_months(dob, ref):
    """Complete calendar months from dob to ref (both date objects)."""
    return (ref.year - dob.year) * 12 + (ref.month - dob.month) - (1 if ref.day < dob.day else 0)


def normalize_name(s):
    """lowercase(trim(collapse_whitespace(s)))."""
    return " ".join(s.split()).lower()


def rhu_div(num, den):
    """round_half_up(num / den) to integer cents."""
    return int((Decimal(num) / Decimal(den)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_pct(cents, pct):
    """round_half_up(cents * pct / 100) to integer cents."""
    return int((Decimal(cents) * Decimal(pct) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        bad("limit and offset must be integers")
    if limit < 1 or limit > 100:
        bad("limit must be between 1 and 100")
    if offset < 0:
        bad("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more
