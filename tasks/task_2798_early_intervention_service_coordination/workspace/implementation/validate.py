"""Payload shape validation (validation ladder step 3: ERR_INVALID_REQUEST)."""
from flask import request

from errors import fail
from store import iso_instant, parse_date, parse_instant, parse_month

MISSING = object()


class Field(object):
    def __init__(self, name, validator, required=True, default=None):
        self.name = name
        self.validator = validator
        self.required = required
        self.default = default


def bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def raw_body():
    data = request.get_json(silent=True)
    if data is None:
        if request.get_data(as_text=True).strip():
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def parse_body(fields):
    data = raw_body()
    declared = set(f.name for f in fields)
    for key in data.keys():
        if key not in declared:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)
    out = {}
    for f in fields:
        if f.name not in data or data[f.name] is None:
            if f.required:
                bad(f.name, "is required")
            out[f.name] = f.default
        else:
            out[f.name] = f.validator(data[f.name], f.name)
    return out


# ---------------------------------------------------------------- validators

def v_str(min_len=1, max_len=None):
    def check(value, name):
        if not isinstance(value, str):
            bad(name, "must be a string")
        text = value
        if len(text.strip()) < min_len:
            bad(name, "must be at least %d characters" % min_len)
        if max_len is not None and len(text) > max_len:
            bad(name, "must be at most %d characters" % max_len)
        return text
    return check


def v_token():
    def check(value, name):
        if not isinstance(value, str):
            bad(name, "must be a string")
        text = value.strip()
        if not text or text != value or text != text.upper() or any(c.isspace() for c in text):
            bad(name, "must be a non-empty uppercase token without whitespace")
        return text
    return check


def v_bool():
    def check(value, name):
        if not isinstance(value, bool):
            bad(name, "must be a boolean")
        return value
    return check


def v_int(lo=None, hi=None):
    def check(value, name):
        if isinstance(value, bool) or not isinstance(value, int):
            bad(name, "must be an integer")
        if lo is not None and value < lo:
            bad(name, "must be at least %d" % lo)
        if hi is not None and value > hi:
            bad(name, "must be at most %d" % hi)
        return value
    return check


def v_num(lo=None, hi=None):
    def check(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad(name, "must be a number")
        if lo is not None and value < lo:
            bad(name, "must be at least %s" % lo)
        if hi is not None and value > hi:
            bad(name, "must be at most %s" % hi)
        return float(value)
    return check


def v_enum(values):
    allowed = tuple(values)

    def check(value, name):
        if not isinstance(value, str):
            bad(name, "must be a string")
        if value not in allowed:
            bad(name, "must be one of %s" % ", ".join(allowed))
        return value
    return check


def v_date():
    def check(value, name):
        if not isinstance(value, str):
            bad(name, "must be an ISO 8601 date string")
        parsed = parse_date(value)
        if parsed is None:
            bad(name, "must be a real calendar date in YYYY-MM-DD form")
        return parsed.isoformat()
    return check


def v_month():
    def check(value, name):
        if not isinstance(value, str):
            bad(name, "must be a YYYY-MM month string")
        parsed = parse_month(value)
        if parsed is None:
            bad(name, "must be a calendar month in YYYY-MM form")
        return parsed
    return check


def v_instant():
    def check(value, name):
        if not isinstance(value, str):
            bad(name, "must be an ISO 8601 UTC timestamp")
        parsed = parse_instant(value)
        if parsed is None:
            bad(name, "must be an ISO 8601 UTC timestamp")
        return iso_instant(parsed)
    return check


def v_id():
    def check(value, name):
        if not isinstance(value, str) or not value.strip():
            bad(name, "must be a non-empty identifier string")
        return value
    return check


def v_list(item_validator, min_items=1, unique=True):
    def check(value, name):
        if not isinstance(value, list):
            bad(name, "must be an array")
        if len(value) < min_items:
            bad(name, "must contain at least %d entries" % min_items)
        out = []
        for item in value:
            out.append(item_validator(item, name))
        if unique and len(set(out)) != len(out):
            bad(name, "must not contain duplicate entries")
        return out
    return check
