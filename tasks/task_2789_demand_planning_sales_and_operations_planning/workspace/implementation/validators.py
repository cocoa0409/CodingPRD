"""Request-shape validation (rejection ladder step 3 -> ERR_INVALID_REQUEST)."""
import json

from flask import request

from errors import bad_request
from util import INT_RE, is_date, is_month

MISSING = object()


def get_body():
    raw = request.get_data()
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise bad_request("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------- strings
def req_string(body, name, allow_empty=False):
    if name not in body or body[name] is None:
        raise bad_request("Field '%s' is required" % name)
    v = body[name]
    if not isinstance(v, str):
        raise bad_request("Field '%s' must be a string" % name)
    if not allow_empty and not v.strip():
        raise bad_request("Field '%s' must be non-empty" % name)
    return v


def opt_string(body, name, default=None, allow_empty=False):
    if not _present(body, name):
        return default
    return req_string(body, name, allow_empty=allow_empty)


# ---------------------------------------------------------------- numbers
def _range_check(name, value, minimum, maximum, exclusive_min, exclusive_max):
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s" % (name, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        raise bad_request("Field '%s' must be > %s" % (name, exclusive_min))
    if exclusive_max is not None and value >= exclusive_max:
        raise bad_request("Field '%s' must be < %s" % (name, exclusive_max))


def req_int(body, name, minimum=None, maximum=None, exclusive_min=None,
            exclusive_max=None):
    if name not in body or body[name] is None:
        raise bad_request("Field '%s' is required" % name)
    v = body[name]
    if not is_int(v):
        raise bad_request("Field '%s' must be an integer" % name)
    _range_check(name, v, minimum, maximum, exclusive_min, exclusive_max)
    return v


def opt_int(body, name, default=None, **kw):
    if not _present(body, name):
        return default
    return req_int(body, name, **kw)


def req_number(body, name, minimum=None, maximum=None, exclusive_min=None,
               exclusive_max=None):
    if name not in body or body[name] is None:
        raise bad_request("Field '%s' is required" % name)
    v = body[name]
    if not is_num(v):
        raise bad_request("Field '%s' must be a number" % name)
    _range_check(name, v, minimum, maximum, exclusive_min, exclusive_max)
    return v


def opt_number(body, name, default=None, **kw):
    if not _present(body, name):
        return default
    return req_number(body, name, **kw)


def req_bool(body, name):
    if name not in body or body[name] is None:
        raise bad_request("Field '%s' is required" % name)
    v = body[name]
    if not isinstance(v, bool):
        raise bad_request("Field '%s' must be a boolean" % name)
    return v


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return req_bool(body, name)


# ---------------------------------------------------------------- enums
def req_enum(body, name, allowed):
    v = req_string(body, name)
    if v not in allowed:
        raise bad_request("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


# ---------------------------------------------------------------- calendars
def req_month(body, name):
    v = req_string(body, name)
    if not is_month(v):
        raise bad_request("Field '%s' must be a YYYY-MM month string" % name)
    return v


def opt_month(body, name, default=None):
    if not _present(body, name):
        return default
    return req_month(body, name)


def req_date(body, name):
    v = req_string(body, name)
    if not is_date(v):
        raise bad_request("Field '%s' must be a YYYY-MM-DD date string" % name)
    return v


def forbid(body, name, reason):
    """Conditionally-forbidden field: must be absent or null."""
    if name in body and body[name] is not None:
        raise bad_request("Field '%s' %s" % (name, reason))


def req_id(body, name):
    return req_string(body, name)


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    return req_string(body, name)


# ---------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not INT_RE.match(raw.strip()):
            raise bad_request("Query parameter 'limit' must be an integer")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not INT_RE.match(raw.strip()):
            raise bad_request("Query parameter 'offset' must be an integer")
        offset = int(raw.strip())
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise bad_request("Query parameter '%s' must be one of %s" % (name, sorted(allowed)))
    return raw


def query_month(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if not is_month(raw):
        raise bad_request("Query parameter '%s' must be a YYYY-MM month string" % name)
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise bad_request("Query parameter '%s' must be a boolean" % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
