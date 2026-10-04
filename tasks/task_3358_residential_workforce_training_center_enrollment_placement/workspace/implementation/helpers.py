"""Request body validation, pagination, and small typed helpers."""
import re
from datetime import date, datetime

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def invalid(msg):
    raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], msg)


def raw_body():
    """Loose body parse: returns the JSON object or None (no error raised)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def get_body():
    """Priority 5 base: body must be a JSON object when present."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        invalid("Request body must be valid JSON")
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object")
    return data


def check_unknown(body, allowed):
    extra = [k for k in body if k not in allowed]
    if extra:
        invalid("Undeclared field(s): {}".format(", ".join(sorted(extra))))


def as_str(body, name, required=False):
    if name not in body:
        if required:
            invalid("Missing required field: {}".format(name))
        return None
    v = body[name]
    if not isinstance(v, str):
        invalid("Field {} must be a string".format(name))
    return v


def as_int(body, name, required=False, lo=None, hi=None):
    if name not in body:
        if required:
            invalid("Missing required field: {}".format(name))
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        invalid("Field {} must be an integer".format(name))
    if lo is not None and v < lo:
        invalid("Field {} must be >= {}".format(name, lo))
    if hi is not None and v > hi:
        invalid("Field {} must be <= {}".format(name, hi))
    return v


def as_number(body, name, required=False, lo=None):
    if name not in body:
        if required:
            invalid("Missing required field: {}".format(name))
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid("Field {} must be a number".format(name))
    if lo is not None and v < lo:
        invalid("Field {} must be >= {}".format(name, lo))
    return v


def as_bool(body, name, required=False):
    if name not in body:
        if required:
            invalid("Missing required field: {}".format(name))
        return None
    v = body[name]
    if not isinstance(v, bool):
        invalid("Field {} must be a boolean".format(name))
    return v


def parse_date_str(v, name):
    if not isinstance(v, str) or not DATE_RE.match(v):
        invalid("Field {} must be a YYYY-MM-DD date".format(name))
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        invalid("Field {} is not a valid calendar date".format(name))
    return v


def as_date(body, name, required=False):
    if name not in body:
        if required:
            invalid("Missing required field: {}".format(name))
        return None
    return parse_date_str(body[name], name)


def as_enum(body, name, values, required=False):
    if name not in body:
        if required:
            invalid("Missing required field: {}".format(name))
        return None
    v = body[name]
    if not isinstance(v, str) or v not in values:
        invalid("Field {} must be one of {}".format(name, ", ".join(values)))
    return v


def as_list_enum(body, name, values, required=False):
    if name not in body:
        if required:
            invalid("Missing required field: {}".format(name))
        return None
    v = body[name]
    if not isinstance(v, list):
        invalid("Field {} must be an array".format(name))
    for item in v:
        if not isinstance(item, str) or item not in values:
            invalid("Field {} members must be one of {}".format(name, ", ".join(values)))
    return list(v)


def pagination_params():
    """limit (default 10, 1..100) and offset (default 0, >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def add_months(date_str, months):
    """Calendar month addition with day clamping; returns YYYY-MM-DD."""
    y, m, d = (int(p) for p in date_str.split("-"))
    m0 = (m - 1) + months
    y += m0 // 12
    m = m0 % 12 + 1
    if m == 12:
        last = date(y + 1, 1, 1).toordinal() - 1
        dim = date.fromordinal(last).day
    else:
        dim = (date(y, m + 1, 1) - date(y, m, 1)).days
    d = min(d, dim)
    return "{:04d}-{:02d}-{:02d}".format(y, m, d)


def date_obj(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def age_years(dob_str, on_date):
    """Whole years between birth date and a date; subtract 1 if the birthday
    has not yet occurred this year."""
    dob = date_obj(dob_str)
    years = on_date.year - dob.year
    if (on_date.month, on_date.day) < (dob.month, dob.day):
        years -= 1
    return years
