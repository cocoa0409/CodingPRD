from flask import request
import errors
import db


def get_body():
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise errors.validation("Request body must be valid JSON")
    if body is None:
        raise errors.validation("Request body must be valid JSON")
    if not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def req_str(body, name):
    v = body.get(name)
    if v is None:
        raise errors.validation(f"Missing required field: {name}")
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"Field {name} must be a non-empty string")
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"Field {name} must be a non-empty string")
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        raise errors.validation(f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise errors.validation(f"Field {name} must be a boolean")
    return v


def opt_bool(body, name, default):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise errors.validation(f"Field {name} must be a boolean")
    return v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field {name} must be an integer")
    return v


def opt_int(body, name):
    v = body.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field {name} must be an integer")
    return v


def opt_str_list(body, name, default):
    v = body.get(name)
    if v is None:
        return list(default)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise errors.validation(f"Field {name} must be an array of strings")
    return list(v)


def opt_date_str(body, name):
    v = opt_str(body, name)
    if v is None:
        return None
    try:
        db.parse_date(v)
    except Exception:
        raise errors.validation(f"Field {name} must be an ISO 8601 date (YYYY-MM-DD)")
    return v


def get_limit_offset():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset
