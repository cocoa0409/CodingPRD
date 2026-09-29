"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

import errors
from errors import ApiError
from store import serialize
from util import fmt_dt, new_request_id, now_real

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now_real()),
    }


def object_response(row_or_dict, status=200):
    data = serialize(row_or_dict) if row_or_dict is not None else {}
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def empty_response(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "%s may not be larger than %d." % (name, maximum))
    return value


def pagination():
    """limit defaults to 10, min 1, max 100; offset defaults to 0."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def paged(collection_rows, filters=None):
    """Apply the domain filters, then limit/offset over creation order."""
    limit, offset = pagination()
    selected = list(collection_rows)
    if filters:
        for field, raw in filters.items():
            if raw is None:
                continue
            selected = [r for r in selected if _matches(r.get(field), raw)]
    total = len(selected)
    return selected[offset:offset + limit], limit, offset, total


def _matches(value, raw):
    if isinstance(value, bool):
        text = str(raw).strip().lower()
        if text in ("true", "1"):
            return value is True
        if text in ("false", "0"):
            return value is False
        return False
    if value is None:
        return False
    if isinstance(value, (int, float)):
        try:
            return float(value) == float(str(raw).strip())
        except (TypeError, ValueError):
            return False
    return str(value) == str(raw)


def query_filters(*names):
    return {name: request.args.get(name) for name in names}
