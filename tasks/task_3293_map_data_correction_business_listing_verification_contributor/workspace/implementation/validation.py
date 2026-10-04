"""Validation helpers shared across routes."""
import re

from errors import raise_err

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise_err("ERR_INVALID_REQUEST", "missing required field: %s" % f)


def require_enum(data, field, allowed):
    val = data.get(field)
    if val not in allowed:
        raise_err("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return val


def opt_enum(data, field, allowed, default=None):
    val = data.get(field, default)
    if val is not None and val not in allowed:
        raise_err("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return val


def require_number(data, field):
    val = data.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise_err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return val


def require_int(data, field):
    val = data.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise_err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return val


def require_str(data, field, min_len=1, max_len=None):
    val = data.get(field)
    if not isinstance(val, str) or len(val) < min_len:
        raise_err("ERR_INVALID_REQUEST", "%s must be a string of at least %d chars" % (field, min_len))
    if max_len is not None and len(val) > max_len:
        raise_err("ERR_INVALID_REQUEST", "%s exceeds max length %d" % (field, max_len))
    return val


def valid_time(s):
    if not isinstance(s, str) or not _TIME_RE.match(s):
        return False
    h, m = int(s[:2]), int(s[3:])
    return 0 <= h <= 23 and 0 <= m <= 59


def get_or_404(store_map, rid):
    rec = store_map.get(rid)
    if rec is None:
        raise_err("ERR_NOT_FOUND", "resource not found: %s" % rid)
    return rec
