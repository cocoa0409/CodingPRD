"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from db import now_iso, public_list
from errors import ApiError

_ID_ALPHABET = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def error_response(err):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is below the minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' exceeds the maximum." % name)
    return value


def pagination_params():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def list_response(records):
    """records: already filtered and sorted list of internal record dicts."""
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": public_list(page)}
    return jsonify(body), 200


# ------------------------------------------------------------- query filters

def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_enum(name, allowed):
    raw = q_str(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is not a permitted value." % name)
    return raw


def q_bool(name):
    raw = q_str(name)
    if raw is None:
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be true or false." % name)
