"""Request body / query-parameter well-formedness (PRD 2.11 step 5)."""
from __future__ import annotations

from flask import request

import util
from errors import ApiError, bad_request


def raw_body() -> dict:
    """Best-effort body read used by the ownership pre-checks (PRD 2.11 step 3)."""
    try:
        body = request.get_json(silent=True)
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def body(required=(), optional=()) -> dict:
    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None
    if payload is None:
        if request.data and request.data.strip():
            raise bad_request("Request body is not valid JSON.")
        payload = {}
    if not isinstance(payload, dict):
        raise bad_request("Request body must be a JSON object.")
    allowed = set(required) | set(optional)
    for key in payload:
        if key not in allowed:
            raise bad_request("Unknown or non-writable body field '%s'." % key)
    for key in required:
        if key not in payload:
            raise bad_request("Missing required field '%s'." % key)
    return payload


# --------------------------------------------------------------------------
# typed accessors
# --------------------------------------------------------------------------

def req_str(payload, key, min_len=1, max_len=None):
    value = payload.get(key)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % key)
    if len(value) < min_len:
        raise bad_request("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' is too long." % key)
    return value


def opt_str(payload, key, default=None, min_len=1, max_len=None):
    if key not in payload or payload.get(key) is None:
        return default
    return req_str(payload, key, min_len=min_len, max_len=max_len)


def req_int(payload, key, minimum=None, maximum=None):
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its allowed minimum." % key)
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' is above its allowed maximum." % key)
    return value


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if key not in payload or payload.get(key) is None:
        return default
    return req_int(payload, key, minimum=minimum, maximum=maximum)


def req_number(payload, key, minimum=None, maximum=None):
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its allowed minimum." % key)
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' is above its allowed maximum." % key)
    return value


def req_bool(payload, key):
    value = payload.get(key)
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return value


def opt_bool(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    return req_bool(payload, key)


def req_enum(payload, key, allowed):
    value = payload.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(payload, key, allowed, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    return req_enum(payload, key, allowed)


def req_dt(payload, key):
    value = payload.get(key)
    try:
        parsed = util.parse_dt(value)
    except Exception:
        raise bad_request("Field '%s' must be an ISO 8601 instant." % key)
    return value, parsed


def opt_dt(payload, key):
    if key not in payload or payload.get(key) is None:
        return None, None
    return req_dt(payload, key)


def req_date(payload, key):
    value = payload.get(key)
    try:
        parsed = util.parse_date(value)
    except Exception:
        raise bad_request("Field '%s' must be a YYYY-MM-DD date." % key)
    return value, parsed


def req_str_array(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return list(default) if default is not None else []
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise bad_request("Field '%s' must be an array of strings." % key)
    return list(value)


def req_id(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise bad_request("Field '%s' must be an identifier string." % key)
    return value


def opt_id(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    return req_id(payload, key)


# --------------------------------------------------------------------------
# pagination + query filters (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        text = args.get("limit")
        try:
            limit = int(str(text).strip())
        except Exception:
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        text = args.get("offset")
        try:
            offset = int(str(text).strip())
        except Exception:
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be 0 or greater.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad_request("Query parameter '%s' is outside its allowed value set." % name)
    return value


def query_str(name):
    return request.args.get(name)


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad_request("Query parameter '%s' must be a boolean." % name)


def query_int(name, minimum=None):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except Exception:
        raise bad_request("Query parameter '%s' must be an integer." % name)
    if minimum is not None and parsed < minimum:
        raise bad_request("Query parameter '%s' is below its allowed minimum." % name)
    return parsed
