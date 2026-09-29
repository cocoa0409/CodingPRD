"""Request-shape validation: ladder rungs 14, 15 and 16.

All three answer ERR_INVALID_REQUEST with HTTP 400, so their relative order
among themselves is immaterial; what matters is that every one of them runs
after existence (rungs 3-13) and before the 422 shape rules (rungs 17-18).
"""

import re

from flask import request

from errors import bad_request
from util import D, is_bool, is_int, is_num, is_str, parse_dt

_INT_RE = re.compile(r"^[+-]?\d+$")


def json_body():
    """Rung 14: the body must parse as a JSON object (or be absent)."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        bad_request("Request body must be a JSON object.")
    return data


def present(body, name):
    return name in body and body[name] is not None


def _require_present(body, name):
    if name not in body or body[name] is None:
        bad_request("Field '%s' is required." % name)


# --------------------------------------------------------------- strings
def req_str(body, name, min_len=1, max_len=None, nonblank=True, pattern=None):
    _require_present(body, name)
    return _check_str(body[name], name, min_len, max_len, nonblank, pattern)


def opt_str(body, name, default=None, min_len=1, max_len=None, nonblank=True,
            pattern=None):
    if not present(body, name):
        return default
    return _check_str(body[name], name, min_len, max_len, nonblank, pattern)


def _check_str(value, name, min_len, max_len, nonblank, pattern):
    if not is_str(value):
        bad_request("Field '%s' must be a string." % name)
    if nonblank and value.strip() == "":
        bad_request("Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        bad_request("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad_request("Field '%s' is longer than %d characters." % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad_request("Field '%s' is malformed." % name)
    return value


def req_email(body, name, max_len=None):
    value = req_str(body, name, min_len=1, max_len=max_len)
    if "@" not in value:
        bad_request("Field '%s' must contain '@'." % name)
    return value


def opt_email(body, name, default=None, max_len=None):
    if not present(body, name):
        return default
    value = _check_str(body[name], name, 1, max_len, True, None)
    if "@" not in value:
        bad_request("Field '%s' must contain '@'." % name)
    return value


# ---------------------------------------------------------------- integers
def req_int(body, name, lo=None, hi=None):
    _require_present(body, name)
    return _check_int(body[name], name, lo, hi)


def opt_int(body, name, default=None, lo=None, hi=None):
    if not present(body, name):
        return default
    return _check_int(body[name], name, lo, hi)


def _check_int(value, name, lo, hi):
    if is_int(value):
        out = value
    elif isinstance(value, float) and float(value).is_integer():
        out = int(value)
    else:
        bad_request("Field '%s' must be an integer." % name)
    if lo is not None and out < lo:
        bad_request("Field '%s' must be at least %s." % (name, lo))
    if hi is not None and out > hi:
        bad_request("Field '%s' must be at most %s." % (name, hi))
    return out


# ----------------------------------------------------------------- numbers
def req_num(body, name, lo=None, hi=None, lo_exclusive=False, hi_exclusive=False):
    _require_present(body, name)
    return _check_num(body[name], name, lo, hi, lo_exclusive, hi_exclusive)


def opt_num(body, name, default=None, lo=None, hi=None, lo_exclusive=False,
            hi_exclusive=False):
    if not present(body, name):
        return default
    return _check_num(body[name], name, lo, hi, lo_exclusive, hi_exclusive)


def _check_num(value, name, lo, hi, lo_exclusive, hi_exclusive):
    if not is_num(value):
        bad_request("Field '%s' must be a number." % name)
    out = D(value)
    if lo is not None:
        if lo_exclusive and out <= D(lo):
            bad_request("Field '%s' must be greater than %s." % (name, lo))
        if not lo_exclusive and out < D(lo):
            bad_request("Field '%s' must be at least %s." % (name, lo))
    if hi is not None:
        if hi_exclusive and out >= D(hi):
            bad_request("Field '%s' must be less than %s." % (name, hi))
        if not hi_exclusive and out > D(hi):
            bad_request("Field '%s' must be at most %s." % (name, hi))
    return out


# ---------------------------------------------------------------- booleans
def req_bool(body, name):
    _require_present(body, name)
    if not is_bool(body[name]):
        bad_request("Field '%s' must be a boolean." % name)
    return body[name]


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    if not is_bool(body[name]):
        bad_request("Field '%s' must be a boolean." % name)
    return body[name]


# ------------------------------------------------------------------- enums
def req_enum(body, name, members):
    _require_present(body, name)
    value = body[name]
    if not is_str(value) or value not in members:
        bad_request("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def opt_enum(body, name, members, default=None):
    if not present(body, name):
        return default
    value = body[name]
    if not is_str(value) or value not in members:
        bad_request("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


# --------------------------------------------------------------- instants
def req_dt(body, name):
    _require_present(body, name)
    parsed = parse_dt(body[name])
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def opt_dt(body, name, default=None):
    if not present(body, name):
        return default
    parsed = parse_dt(body[name])
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 instant." % name)
    return parsed


# ------------------------------------------------------------ foreign keys
def req_fk(body, name):
    """A body foreign key: must be a present, non-empty string (rung 14)."""
    _require_present(body, name)
    value = body[name]
    if not is_str(value) or value.strip() == "":
        bad_request("Field '%s' must be a non-empty string." % name)
    return value


def lookup_fk(body, name):
    """A body foreign key resolved *before* the rung-14 shape pass.

    Existence (rungs 3-13) outranks request shape (rung 14), so a body FK that
    is present and a non-empty string must be resolved first even when some
    other field of the same body is missing or mistyped. When the key itself is
    absent or not a usable string there is nothing to resolve: this returns
    None and the caller re-reads it with req_fk/opt_fk during the shape pass,
    which raises the rung-14 rejection then.
    """
    if not present(body, name):
        return None
    value = body[name]
    if not is_str(value) or value.strip() == "":
        return None
    return value


def opt_fk(body, name):
    if not present(body, name):
        return None
    value = body[name]
    if not is_str(value) or value.strip() == "":
        bad_request("Field '%s' must be a non-empty string." % name)
    return value


# --------------------------------------------------------------- pagination
def pagination():
    """Rung 15: limit is an integer in [1,100]; offset is an integer >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            bad_request("Query parameter 'limit' must be an integer.")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset.strip()):
            bad_request("Query parameter 'offset' must be an integer.")
        offset = int(raw_offset.strip())
        if offset < 0:
            bad_request("Query parameter 'offset' must be 0 or greater.")
    return limit, offset


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return "__no_match__"


def query_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    text = value.strip()
    if not _INT_RE.match(text):
        return "__no_match__"
    return int(text)


_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def query_req_int(name, lo=None, hi=None):
    """A query parameter that carries real input rather than a filter."""
    value = request.args.get(name)
    if value is None:
        bad_request("Query parameter '%s' is required." % name)
    text = value.strip()
    if not _INT_RE.match(text):
        bad_request("Query parameter '%s' must be an integer." % name)
    out = int(text)
    if lo is not None and out < lo:
        bad_request("Query parameter '%s' must be at least %s." % (name, lo))
    if hi is not None and out > hi:
        bad_request("Query parameter '%s' must be at most %s." % (name, hi))
    return out


def query_num(name, default=None, lo=None):
    value = request.args.get(name)
    if value is None:
        return default
    text = value.strip()
    if not _NUM_RE.match(text):
        bad_request("Query parameter '%s' must be a number." % name)
    out = D(text)
    if lo is not None and out < D(lo):
        bad_request("Query parameter '%s' must be at least %s." % (name, lo))
    return out


def apply_filters(rows, spec):
    """spec: list of (row_field, filter_value). None means unfiltered."""
    out = rows
    for field, wanted in spec:
        if wanted is None:
            continue
        if wanted == "__no_match__":
            return []
        out = [r for r in out if r.get(field) == wanted]
    return out


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
