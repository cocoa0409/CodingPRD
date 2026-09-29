"""Response envelope helpers (meta / response_type / data)."""

import json
import random
import string

from flask import Response, request

import db
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": db.now_str(),
    }


def _json_response(body, status):
    return Response(
        json.dumps(body, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    return _json_response(body, status)


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return _json_response(body, 200)


def error_response(err):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _json_response(body, err.http_status)


# ------------------------------------------------------------------ pagination

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _to_int(text, fallback):
    if text is None:
        return fallback
    text = text.strip()
    if text == "":
        return fallback
    try:
        return int(text)
    except (TypeError, ValueError):
        return fallback


def pagination():
    """Return the effective (limit, offset) after clamping to declared bounds."""
    limit = _to_int(request.args.get("limit"), LIMIT_DEFAULT)
    offset = _to_int(request.args.get("offset"), OFFSET_DEFAULT)
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < OFFSET_MIN:
        offset = OFFSET_MIN
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def body_json():
    """Parse the JSON request body, tolerating an absent body as {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def raw_body_json():
    """Parse the body without raising; used for pre-shape client-scope peeking."""
    raw = request.get_data(cache=True, as_text=True)
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
