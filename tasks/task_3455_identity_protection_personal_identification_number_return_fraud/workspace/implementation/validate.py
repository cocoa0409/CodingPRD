"""Payload-shape validation helpers (priority-14 checks) and pagination.

All helpers raise ERR_INVALID_REQUEST (HTTP 400) on violation.
"""
import re
from datetime import date

from flask import request

from errors import err
from store import parse_ts

TIN_RE = re.compile(r"^\d{9}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    """Return the JSON request body as a dict ({} when absent or not an object)."""
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def invalid(message):
    err("ERR_INVALID_REQUEST", message)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_tin(v):
    return isinstance(v, str) and bool(TIN_RE.match(v))


def is_date_str(v):
    if not isinstance(v, str) or not DATE_RE.match(v):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def req_field(b, name):
    if name not in b or b[name] is None:
        invalid("Missing required field: %s" % name)
    return b[name]


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str) or v == "":
        invalid("Field %s must be a non-empty string" % name)
    return v


def opt_str(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not isinstance(v, str):
        invalid("Field %s must be a string" % name)
    return v


def req_int(b, name):
    v = req_field(b, name)
    if not is_int(v):
        invalid("Field %s must be an integer" % name)
    return v


def opt_int(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not is_int(v):
        invalid("Field %s must be an integer" % name)
    return v


def req_enum(b, name, allowed):
    v = req_field(b, name)
    if v not in allowed:
        invalid("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(b, name, allowed, default=None):
    v = b.get(name, default)
    if v is not None and v not in allowed:
        invalid("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def req_tin(b, name):
    v = req_field(b, name)
    if not is_tin(v):
        invalid("Field %s must be exactly 9 digits" % name)
    return v


def req_date(b, name):
    v = req_field(b, name)
    if not is_date_str(v):
        invalid("Field %s must be an ISO 8601 date (YYYY-MM-DD)" % name)
    return v


def req_datetime(b, name):
    v = req_field(b, name)
    dt = parse_ts(v)
    if dt is None:
        invalid("Field %s must be an ISO 8601 timestamp" % name)
    return dt


def req_nonneg_int(b, name):
    v = req_int(b, name)
    if v < 0:
        invalid("Field %s must be >= 0" % name)
    return v


def pagination():
    """Parse limit/offset query params: default 10/0, clamp to [1,100]/[0,inf)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sorted_created(rows):
    """Sort internal records by created_at ASC (insertion order as tiebreak)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def page(rows, limit, offset):
    """Sort by created_at ASC and apply offset/limit; returns (page, total)."""
    ordered = sorted_created(rows)
    total = len(ordered)
    return ordered[offset:offset + limit], total
