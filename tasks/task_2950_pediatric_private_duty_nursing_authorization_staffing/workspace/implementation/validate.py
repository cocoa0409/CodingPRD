"""Request-shape validation (PRD 2.8 check 7) and pagination parsing (PRD 2.3)."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from envelope import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from errors import fail
from timeutil import parse_date, parse_instant

INVALID = "ERR_INVALID_REQUEST"
_INT_RE = re.compile(r"^[+-]?\d+$")
_NPI_RE = re.compile(r"^\d{10}$")

SKILLS = ("TRACH", "VENT", "FEEDING_TUBE", "SEIZURE_RESCUE")


def bad(message):
    fail(INVALID, message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, maxlen=None, minlen=1):
    if not present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if len(value.strip()) < minlen:
        bad("Field '%s' must be non-blank." % key)
    if maxlen is not None and len(value) > maxlen:
        bad("Field '%s' must be at most %d characters." % (key, maxlen))
    return value


def opt_str(data, key, default=None, maxlen=None):
    if not present(data, key):
        return default
    return req_str(data, key, maxlen=maxlen, minlen=0)


def req_enum(data, key, allowed):
    if not present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not present(data, key):
        return default
    return req_enum(data, key, allowed)


def _to_int(value, key):
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if float(value).is_integer():
            return int(value)
        bad("Field '%s' must be an integer." % key)
    if isinstance(value, str) and _INT_RE.match(value.strip()):
        return int(value.strip())
    bad("Field '%s' must be an integer." % key)


def req_int(data, key, lo=None, hi=None):
    if not present(data, key):
        bad("Field '%s' is required." % key)
    number = _to_int(data[key], key)
    if lo is not None and number < lo:
        bad("Field '%s' must be at least %s." % (key, lo))
    if hi is not None and number > hi:
        bad("Field '%s' must be at most %s." % (key, hi))
    return number


def opt_int(data, key, default=None, lo=None, hi=None):
    if not present(data, key):
        return default
    return req_int(data, key, lo=lo, hi=hi)


def _to_decimal(value, key):
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % key)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            bad("Field '%s' must be a number." % key)
    bad("Field '%s' must be a number." % key)


def req_hours(data, key, hi=None):
    """A positive hour figure; check 7 requires numbers to be strictly positive."""
    if not present(data, key):
        bad("Field '%s' is required." % key)
    number = _to_decimal(data[key], key)
    if number <= 0:
        bad("Field '%s' must be strictly positive." % key)
    if hi is not None and number > hi:
        bad("Field '%s' must be at most %s." % (key, hi))
    return number


def opt_hours(data, key, default=None, hi=None):
    if not present(data, key):
        return default
    return req_hours(data, key, hi=hi)


def req_instant(data, key):
    if not present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 instant." % key)
    parsed = parse_instant(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def opt_instant(data, key, default=None):
    if not present(data, key):
        return default
    return req_instant(data, key)


def req_date(data, key):
    if not present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD date." % key)
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return parsed


def opt_bool(data, key, default=False):
    if not present(data, key):
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    bad("Field '%s' must be a boolean." % key)


def req_npi(data, key):
    value = req_str(data, key, maxlen=None)
    if not _NPI_RE.match(value.strip()):
        bad("Field '%s' must be exactly ten digits." % key)
    return value.strip()


def req_skills(data, key):
    if not present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list) or len(value) == 0:
        bad("Field '%s' must be a non-empty array of skills." % key)
    if len(value) > len(SKILLS):
        bad("Field '%s' must hold at most %d distinct skills." % (key, len(SKILLS)))
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in SKILLS:
            bad("Field '%s' must contain only %s." % (key, ", ".join(SKILLS)))
        if item in seen:
            bad("Field '%s' members must be distinct." % key)
        seen.append(item)
    return seen


def opt_id_list(data, key, default=None):
    if not present(data, key):
        return list(default or [])
    value = data[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            bad("Field '%s' must contain identifier strings." % key)
        out.append(item)
    return out


def req_fk(data, key):
    if not present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be an identifier string." % key)
    return value


def opt_fk(data, key, default=None):
    if not present(data, key):
        return default
    return req_fk(data, key)


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw = request.args.get("limit")
    if raw is not None and raw.strip() != "":
        if not _INT_RE.match(raw.strip()):
            bad("Query parameter 'limit' must be an integer.")
        limit = int(raw.strip())
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("Query parameter 'limit' must be between %d and %d."
                % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    raw = request.args.get("offset")
    if raw is not None and raw.strip() != "":
        if not _INT_RE.match(raw.strip()):
            bad("Query parameter 'offset' must be an integer.")
        offset = int(raw.strip())
        if offset < PAGE_OFFSET_DEFAULT:
            bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit]


def query_value(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw if raw != "" else None


def query_enum(name, allowed):
    raw = query_value(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_instant(name):
    raw = query_value(name)
    if raw is None:
        return None
    parsed = parse_instant(raw)
    if parsed is None:
        bad("Query parameter '%s' must be an ISO 8601 instant." % name)
    return parsed
