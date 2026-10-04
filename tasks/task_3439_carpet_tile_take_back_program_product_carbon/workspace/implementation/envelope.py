"""Response envelope builders (PRD 2.2 success/error, PRD 2.3 pagination).

Success: {"meta": {"api_request_id", "api_request_timestamp"}, "response_type":
"object"|"array", "data": ...}; list responses add limit/offset/total_count/
has_more into meta. Error: meta (request id + timestamp only), response_type
"error", data {"error_id", "message"}. The meta timestamp comes from the
logical clock — the server never consults wall-clock time (PRD 2.5).
"""
import random
import string

from flask import jsonify

from store import STORE
from util import created_key, fmt_dt, pagination_params


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(STORE.now()),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(serialized_items_total, limit, offset):
    total = len(serialized_items_total)
    page = serialized_items_total[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success(page, 200, "array", pagination)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.status
    return resp


def list_endpoint(items, args, filters, serializer):
    """Filter (exact match on the given fields), sort by creation ascending,
    paginate per PRD 2.3, and wrap in the list envelope."""
    filtered = [e for e in items if all(e.get(k) == v for k, v in filters.items())]
    filtered.sort(key=created_key)
    limit, offset = pagination_params(args)
    return success_list([serializer(e) for e in filtered], limit, offset)
