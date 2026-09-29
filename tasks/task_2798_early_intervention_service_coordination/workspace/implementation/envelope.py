"""Response envelope helpers: meta / response_type / data."""
from flask import jsonify, request

from errors import ApiError, CATALOG, fail
from store import now_iso, request_id


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": now_iso()}


def single(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def collection(rows, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_body(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_SYNTACTIC_MAX = 200
LIMIT_EFFECTIVE_MAX = 100
OFFSET_DEFAULT = 0


def _as_int(raw):
    if raw is None:
        return None
    text = raw.strip()
    if text == "" or not (text.isdigit() or (text[0] == "-" and text[1:].isdigit())):
        fail("ERR_INVALID_PAGINATION",
             "Pagination parameters must be integers.")
    return int(text)


def pagination():
    """Read and validate limit/offset from the query string."""
    limit = _as_int(request.args.get("limit"))
    offset = _as_int(request.args.get("offset"))
    if limit is None:
        limit = LIMIT_DEFAULT
    elif limit < LIMIT_MIN or limit > LIMIT_SYNTACTIC_MAX:
        fail("ERR_INVALID_PAGINATION",
             "limit must be between %d and %d." % (LIMIT_MIN, LIMIT_SYNTACTIC_MAX))
    if offset is None:
        offset = OFFSET_DEFAULT
    elif offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset must be zero or greater.")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    effective = min(limit, LIMIT_EFFECTIVE_MAX)
    page = rows[offset:offset + effective]
    return collection([serializer(r) for r in page], limit, offset, total)
