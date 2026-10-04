"""Shared validation, date/calendar, and decimal helpers."""
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import fail

TWO_PLACES = Decimal("0.01")


# --- JSON body ------------------------------------------------------------

def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


# --- dates / calendar -----------------------------------------------------

def parse_date(s):
    """Strict YYYY-MM-DD -> date, else None."""
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_iso_dt(s):
    """ISO 8601 datetime (accepts trailing Z) -> aware UTC datetime, else None."""
    if not isinstance(s, str):
        return None
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_calendar_months(d, n):
    """True calendar-month arithmetic (PRD §2.4), clamping the day."""
    total = d.year * 12 + (d.month - 1) + n
    y, m = divmod(total, 12)
    m += 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_days(d, n):
    return d + timedelta(days=n)


# --- decimals -------------------------------------------------------------

def dec(v):
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def q2(x):
    """Round-half-up to exactly 2 decimal places (PRD §2.6)."""
    return dec(x).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_half_up_int(x):
    return int(dec(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- field validators (ERR_INVALID_REQUEST) --------------------------------

def need(b, name):
    if name not in b or b[name] is None:
        fail("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    return b[name]


def v_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", "field %s must be an integer" % name)
    return v


def v_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", "field %s must be a number" % name)
    return v


def v_bool(v, name):
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "field %s must be a boolean" % name)
    return v


def v_str(v, name):
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", "field %s must be a string" % name)
    return v


def v_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_INVALID_REQUEST", "field %s must be one of %s" % (name, sorted(allowed)))
    return v


def v_date(v, name):
    d = parse_date(v)
    if d is None:
        fail("ERR_INVALID_REQUEST", "field %s must be a YYYY-MM-DD date" % name)
    return d


def v_range(v, name, lo=None, hi=None, lo_inclusive=True, hi_inclusive=True):
    d = dec(v)
    if lo is not None:
        if (d < lo) if lo_inclusive else (d <= lo):
            fail("ERR_INVALID_REQUEST", "field %s out of range" % name)
    if hi is not None:
        if (d > hi) if hi_inclusive else (d >= hi):
            fail("ERR_INVALID_REQUEST", "field %s out of range" % name)
    return v


def v_evidence_items(v, name="evidence_items"):
    if not isinstance(v, list) or len(v) < 1:
        fail("ERR_INVALID_REQUEST", "field %s must contain at least one item" % name)
    for item in v:
        if not isinstance(item, dict) or "doc_type" not in item or "uri" not in item:
            fail("ERR_INVALID_REQUEST", "each %s entry must pair doc_type with uri" % name)
    return v


# --- pagination (PRD §2.3) --------------------------------------------------

def pagination_params():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def page_of(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
