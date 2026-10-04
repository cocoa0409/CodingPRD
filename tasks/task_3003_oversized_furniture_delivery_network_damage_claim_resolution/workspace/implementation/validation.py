"""Request-field validation helpers (ERR_INVALID_REQUEST checks)."""
import math
import re

from errors import err_invalid_request


def get_body(req):
    if not req.data:
        return {}
    try:
        body = req.get_json(force=True)
    except Exception:
        raise err_invalid_request("Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def req_string(body, name):
    v = body.get(name)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise err_invalid_request("Field '%s' is required and must be a non-empty string" % name)
    return v


def opt_string(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err_invalid_request("Field '%s' must be a string" % name)
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request("Field '%s' is required and must be an integer" % name)
    return v


def opt_int(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request("Field '%s' must be an integer" % name)
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err_invalid_request("Field '%s' is required and must be a boolean" % name)
    return v


def _is_finite_number(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return math.isfinite(v)
    return False


def req_number(body, name):
    v = body.get(name)
    if not _is_finite_number(v):
        raise err_invalid_request("Field '%s' is required and must be a finite number" % name)
    return v


def req_enum(body, name, allowed):
    v = req_string(body, name)
    if v not in allowed:
        raise err_invalid_request("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def req_string_list(body, name):
    v = body.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise err_invalid_request("Field '%s' is required and must be a list of strings" % name)
    return v


_ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def req_datetime(body, name):
    from clock import _parse_iso

    v = body.get(name)
    if not isinstance(v, str) or not _ISO_DT_RE.match(v):
        raise err_invalid_request("Field '%s' is required and must be an ISO 8601 datetime" % name)
    try:
        return _parse_iso(v)
    except Exception:
        raise err_invalid_request("Field '%s' must be a valid ISO 8601 datetime" % name)


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(body, name):
    from datetime import date as _date

    v = body.get(name)
    if not isinstance(v, str) or not _ISO_DATE_RE.match(v):
        raise err_invalid_request("Field '%s' is required and must be an ISO date (YYYY-MM-DD)" % name)
    try:
        y, m, d = int(v[0:4]), int(v[5:7]), int(v[8:10])
        return _date(y, m, d)
    except Exception:
        raise err_invalid_request("Field '%s' must be a valid ISO date" % name)


def parse_pagination(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(str(raw_limit), 10)
        except Exception:
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(str(raw_offset), 10)
        except Exception:
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset
