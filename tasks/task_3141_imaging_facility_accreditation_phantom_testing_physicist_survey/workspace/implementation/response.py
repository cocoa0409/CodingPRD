"""Standard response envelope (PRD §2.2)."""

import random
import string

import flask

import db

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(15))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return flask.jsonify(body), status


def err(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return flask.jsonify(body), http_status


def paginate(rows, params):
    """Apply limit/offset from the query string and return (page, meta_block).

    `limit` defaults to 10 and must fall within the inclusive range 1 to 100;
    `offset` defaults to 0.
    """
    raw_limit = params.get("limit")
    limit = _int_param(raw_limit, 10)
    # `limit` must fall within the inclusive range 1 to 100.
    if limit < 1 or limit > 100:
        from errors import fail
        fail("ERR_INVALID_REQUEST", "limit must be within the inclusive range 1 to 100")
    offset = _int_param(params.get("offset"), 0)
    if offset < 0:
        offset = 0
    total = len(rows)
    page = rows[offset: offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


def _int_param(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default