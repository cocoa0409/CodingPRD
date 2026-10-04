"""Standard response envelope helpers per PRD section 2.2 / 2.3."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from db import fmt_ts

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        # Envelope timestamps are real server timestamps (PRD 2.2 example uses
        # wall-clock-looking values); business logic uses the logical clock.
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_obj(data, http_status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), http_status


def ok_list(items, limit, offset, total_count, http_status=200):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), http_status


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
