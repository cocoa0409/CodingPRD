"""Response envelope helpers (PRD section 2.2).

Success:

    { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
      "response_type": "object" | "array", "data": {} }

List responses add the four pagination fields *inside* meta: limit, offset,
total_count, has_more.  Errors carry an error envelope whose meta holds only the
request id and timestamp, with data { error_id, message }.
"""

import uuid
from datetime import datetime, timezone

import flask


def new_request_id():
    return "req_" + uuid.uuid4().hex[:16].upper()


def utc_now_iso():
    """ISO 8601 UTC with exactly three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def meta(request_id=None):
    return {
        "api_request_id": request_id or new_request_id(),
        "api_request_timestamp": utc_now_iso(),
    }


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return flask.jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    has_more = (offset + limit) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return ok(items, status=status, response_type="array", pagination=pagination)


def error(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return flask.jsonify(body), http_status