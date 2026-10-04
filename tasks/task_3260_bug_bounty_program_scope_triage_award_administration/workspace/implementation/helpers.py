"""Common entity helpers: id minting, common fields, mutation touch, body
validation utilities."""
import uuid

from errors import raise_err, ERR_INVALID_REQUEST
import clock


def new_id():
    return str(uuid.uuid4())


def base_entity():
    now = clock.now()
    return {
        "id": new_id(),
        "created_at": clock.iso_ms(now),
        "updated_at": clock.iso_ms(now),
        "version": 1,
        "_created_dt": now,
    }


def touch(entity):
    entity["updated_at"] = clock.iso_now_ms()
    entity["version"] = entity.get("version", 1) + 1


def get_body():
    from flask import request

    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def reject_unknown_fields(body, allowed):
    for k in body:
        if k not in allowed:
            raise_err(ERR_INVALID_REQUEST, f"Unknown or read-only field: {k}")


def require_int(body, field, lo=None, hi=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if lo is not None and v < lo:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} out of range")
    if hi is not None and v > hi:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} out of range")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def parse_pagination(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
