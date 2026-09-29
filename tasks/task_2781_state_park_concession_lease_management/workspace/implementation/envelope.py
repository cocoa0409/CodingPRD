"""Response envelope, pagination and collection filtering."""
import json
import random
import string
from decimal import Decimal

from flask import Response, request

from errors import ApiError
from store import now_iso

ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("not JSON serializable: %r" % (obj,))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _clean(row):
    if row is None:
        return {}
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def _respond(payload, status):
    body = json.dumps(payload, default=_json_default)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data) if isinstance(data, dict) else data,
    }
    return _respond(payload, status)


def created(data):
    return ok(data, 201)


def fail(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, status)


def _page_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not (text.lstrip("-").isdigit()):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is below its minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is above its maximum" % name)
    return value


def sort_key(row):
    return (row["created_at"], row["_seq"])


def listing(collection, filters=()):
    """Filter, order by created_at ascending (insertion order breaks ties),
    then paginate. Unrecognized query parameters are ignored."""
    limit = _page_arg("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _page_arg("offset", PAGE_OFFSET_DEFAULT, 0, None)
    rows = list(collection.values())
    for field in filters:
        wanted = request.args.get(field)
        if wanted is None:
            continue
        rows = [r for r in rows if r.get(field) is not None and str(r.get(field)) == wanted]
    rows.sort(key=sort_key)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": [_clean(r) for r in page],
    }
    return _respond(payload, 200)
