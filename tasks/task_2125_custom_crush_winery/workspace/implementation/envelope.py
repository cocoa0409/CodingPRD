"""Standard response envelope (PRD 2.2) and JSON body handling."""

import json
import random
import string
from decimal import Decimal

from flask import Response, request

from errors import ApiError, ERR_INVALID_REQUEST
from store import db, iso

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("not JSON serializable: %r" % (obj,))


def _dump(payload):
    return json.dumps(payload, default=_default)


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def respond(data, status=200, response_type="object", pagination=None):
    payload = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return Response(_dump(payload), status=status, mimetype="application/json")


def respond_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return respond(items, 200, "array", pagination)


def respond_error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(_dump(payload), status=status, mimetype="application/json")


def parse_body():
    """Parse the JSON body preserving decimal literals exactly.

    Returns (body, parse_error). The error is deferred so the ladder can run
    role authorization (rung 3) before request shape (rung 5).
    """
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}, None
    try:
        body = json.loads(raw, parse_float=Decimal)
    except Exception:
        return None, ApiError(ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if not isinstance(body, dict):
        return None, ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body, None
