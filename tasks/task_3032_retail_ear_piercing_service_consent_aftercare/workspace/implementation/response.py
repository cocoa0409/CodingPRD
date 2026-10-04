"""Standard response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

ALPHANUM = string.ascii_letters + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(18))


def _meta(timestamp, pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": timestamp,
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, response_type="object", status=200, pagination=None):
    from db import fmt_now
    return jsonify({
        "meta": _meta(fmt_now(), pagination),
        "response_type": response_type,
        "data": data,
    }), status


def object_response(entity, status=200):
    return success(entity.to_dict() if hasattr(entity, "to_dict") else entity,
                   "object", status)


def array_response(rows, status=200):
    return success([r.to_dict() if hasattr(r, "to_dict") else r for r in rows],
                   "array", status)


def error_response(error_id, message, http_status):
    from db import fmt_now
    return jsonify({
        "meta": _meta(fmt_now()),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status


def pagination_meta(limit, offset, total_count):
    return {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + limit < total_count,
    }


def paginate(rows, limit, offset):
    """Rows are already sorted; page them and return (page, meta)."""
    total_count = len(rows)
    page = rows[offset:offset + limit]
    return page, pagination_meta(limit, offset, total_count)