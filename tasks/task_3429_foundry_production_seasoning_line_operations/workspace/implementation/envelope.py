"""Response envelope helpers implementing PRD section 2.2 / 2.3."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

import store


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta_base():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(status, error_id, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def list_payload(items, serializer, limit, offset):
    """Sort by created_at ASC (ties broken by insertion sequence) and paginate."""
    ordered = sorted(items, key=store.sort_key)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success([serializer(e) for e in page], response_type="array", pagination=pagination)
