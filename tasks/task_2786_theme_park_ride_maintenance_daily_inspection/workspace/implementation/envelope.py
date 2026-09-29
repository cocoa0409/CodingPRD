"""Standard response envelope (PRD section 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

import store
from errors import invalid

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return jsonify(error_body(error_id, message)), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    raw = raw.strip()
    negative = raw.startswith("-")
    digits = raw[1:] if negative or raw.startswith("+") else raw
    if not digits.isdigit():
        invalid("%s must be an integer." % name)
    value = int(raw)
    if minimum is not None and value < minimum:
        invalid("%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("%s must be at most %d." % (name, maximum))
    return value


def page_params():
    """Read and validate the limit/offset query parameters."""
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


_NOMATCH = object()


def _wanted(field, kind):
    raw = request.args.get(field)
    if raw is None:
        return None
    if kind == "bool":
        low = raw.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return _NOMATCH
    if kind == "int":
        text = raw.strip()
        digits = text[1:] if text.startswith(("-", "+")) else text
        if not digits.isdigit():
            return _NOMATCH
        return int(text)
    return raw


def list_response(source_rows, serializer, filters=(), order=()):
    """Filter, order and paginate a collection.

    Filtering and ordering both read the *serialized* view, so derived fields
    (operational_posture, ndt_status, certification status, ...) filter and sort
    on their freshly derived values. The insertion sequence is the final
    tie-break of every ordering.
    """
    pairs = [(r, serializer(r)) for r in source_rows]
    for field, kind in filters:
        wanted = _wanted(field, kind)
        if wanted is None:
            continue
        if wanted is _NOMATCH:
            pairs = []
            break
        pairs = [p for p in pairs if p[1].get(field) == wanted]

    def sort_key(pair):
        row, view = pair
        out = []
        for key in order:
            value = key(row, view) if callable(key) else view.get(key)
            out.append((value is None, value if value is not None else ""))
        out.append((False, row["_seq"]))
        return out

    pairs = sorted(pairs, key=sort_key)
    limit, offset = page_params()
    total = len(pairs)
    page = pairs[offset:offset + limit]
    return listing([view for _, view in page], limit, offset, total)
