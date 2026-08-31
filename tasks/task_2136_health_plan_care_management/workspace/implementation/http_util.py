"""Response envelope, auth extraction, pagination and body-shape validators."""
import json
from decimal import Decimal

from flask import jsonify, request

import core
from core import parse_date, parse_instant, rhu
from errors import ApiError


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": core.request_id(),
        "api_request_timestamp": core.wall_now_iso(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status


# --------------------------------------------------------------------------
# Auth (ladder steps 1 and 2)
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in core.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


# --------------------------------------------------------------------------
# Pagination (ladder step 4)
# --------------------------------------------------------------------------
def _as_int(raw):
    text = str(raw).strip()
    if text == "":
        return None
    neg = False
    if text[0] in "+-":
        neg = text[0] == "-"
        text = text[1:]
    if not text.isdigit():
        return None
    value = int(text)
    return -value if neg else value


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        value = _as_int(raw)
        if value is None or value < 1 or value > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
        limit = value
    if "offset" in args:
        raw = args.get("offset")
        value = _as_int(raw)
        if value is None or value < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
        offset = value
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# --------------------------------------------------------------------------
# Body shape validators (ladder step 3)
# --------------------------------------------------------------------------
def body():
    raw = request.get_data(cache=True, parse_form_data=False)
    if raw is None or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def req_str(data, field, allow_empty=False):
    if field not in data:
        _bad(field, "is required")
    value = data.get(field)
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and not value.strip():
        _bad(field, "must be non-empty")
    return value


def opt_str(data, field, default=None, allow_empty=False):
    if field not in data or data.get(field) is None:
        return default
    return req_str(data, field, allow_empty=allow_empty)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_enum(data, field, allowed)


def req_int(data, field, minimum=None, maximum=None):
    if field not in data:
        _bad(field, "is required")
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_decimal(data, field, gt=None, ge=None, places=1):
    if field not in data:
        _bad(field, "is required")
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    dec = Decimal(str(value))
    if gt is not None and dec <= Decimal(str(gt)):
        _bad(field, "must be > %s" % gt)
    if ge is not None and dec < Decimal(str(ge)):
        _bad(field, "must be >= %s" % ge)
    return rhu(dec, places)


def req_instant(data, field):
    raw = req_str(data, field)
    parsed = parse_instant(raw)
    if parsed is None:
        _bad(field, "must be an ISO 8601 instant")
    return parsed


def req_date_str(data, field):
    raw = req_str(data, field)
    if parse_date(raw) is None:
        _bad(field, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return raw


def req_str_array(data, field, allowed=None, item_check=None):
    if field not in data:
        _bad(field, "is required")
    value = data.get(field)
    if not isinstance(value, list) or len(value) == 0:
        _bad(field, "must be a non-empty array")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad(field, "must contain only non-empty strings")
        if allowed is not None and item not in allowed:
            _bad(field, "must be a subset of %s" % ", ".join(allowed))
        if item_check is not None and not item_check(item):
            _bad(field, "contains an invalid entry")
    return list(value)


def is_state_code(value):
    return isinstance(value, str) and len(value) == 2 and value.isalpha() and value.isupper()


def req_state_code(data, field):
    value = req_str(data, field)
    if not is_state_code(value):
        _bad(field, "must be exactly two uppercase letters")
    return value
