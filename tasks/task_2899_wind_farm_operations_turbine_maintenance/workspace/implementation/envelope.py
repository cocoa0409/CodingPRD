"""Response envelope, serialization and pagination."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from errors import ApiError
from store import DB, iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(DB.now()),
    }


def _value(v):
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    return v


def serialize(row):
    """Public projection of a stored row: every non-underscore field."""
    out = {}
    for key, val in row.items():
        if key.startswith("_"):
            continue
        out[key] = _value(val)
    return out


def ok(row, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": serialize(row) if row is not None else {},
    }
    return jsonify(body), status


def created(row):
    return ok(row, 201)


def ok_raw(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in page],
    }
    return jsonify(body), 200


def error_response(error_id, message):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    from errors import ERROR_STATUS

    return jsonify(body), ERROR_STATUS[error_id]


def page_params(args):
    """limit/offset with the declared bounds; anything else is malformed."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def filter_enum(args, name, members):
    """Read an enum-valued query filter, validating it against its members."""
    raw = args.get(name)
    if raw is None:
        return None
    if raw not in members:
        raise ApiError(
            "ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(members))
        )
    return raw


def filter_bool(args, name):
    raw = args.get(name)
    if raw is None:
        return None
    low = str(raw).strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def listing(rows, args, filters):
    """Conjunctive query filters plus pagination, in created_at order."""
    limit, offset = page_params(args)
    for param, field, kind, members in filters:
        if kind == "enum":
            value = filter_enum(args, param, members)
        elif kind == "bool":
            value = filter_bool(args, param)
        else:
            value = args.get(param)
        if value is None:
            continue
        rows = [r for r in rows if r[field] == value]
    return ok_list(rows, limit, offset)
