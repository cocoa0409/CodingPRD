"""Request body and query validation helpers (priority-3 checks)."""
import json
import math

from flask import request

from db import parse_dt
from errors import raise_err


def get_body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise_err("ERR_VALIDATION", "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise_err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _bad(field, msg):
    raise_err("ERR_VALIDATION", "%s: %s" % (field, msg))


def req_str(body, field):
    if field not in body or not isinstance(body[field], str):
        _bad(field, "required string")
    return body[field]


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], str):
        _bad(field, "must be a string")
    return body[field]


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return v


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def req_number(body, field):
    if field not in body or not is_number(body[field]):
        _bad(field, "required finite number")
    return body[field]


def req_int(body, field, minimum=None):
    if field not in body or isinstance(body[field], bool) or not isinstance(body[field], int):
        _bad(field, "required integer")
    v = body[field]
    if minimum is not None and v < minimum:
        _bad(field, "must be >= %d" % minimum)
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        _bad(field, "must be a boolean")
    return body[field]


def req_dt(body, field):
    if field not in body:
        _bad(field, "required ISO 8601 timestamp")
    dt = parse_dt(body[field])
    if dt is None:
        _bad(field, "must be an ISO 8601 timestamp")
    return dt


def opt_fk(body, field):
    """Optional nullable foreign-key string; None when absent or null."""
    if field not in body or body[field] is None:
        return None
    if not isinstance(body[field], str):
        _bad(field, "must be a string id")
    return body[field]


def pagination_params():
    """limit defaults 10 (min 1, max 100); offset defaults 0 (min 0)."""
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "limit must be an integer")
        limit = max(1, min(100, limit))
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "offset must be an integer")
        offset = max(0, offset)
    return limit, offset
