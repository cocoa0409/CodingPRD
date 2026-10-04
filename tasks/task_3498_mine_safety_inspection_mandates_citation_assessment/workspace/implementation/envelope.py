"""Response envelope (PRD section 2.2) and pagination (PRD section 2.3)."""
import uuid

from flask import jsonify, request

import clock
from constants import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import ApiError, ERR_INVALID_REQUEST


def _request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.render_system(clock.now()),
    }


def ok_object(data, status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(page, limit, offset, total):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_body(api_error):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


def _parse_int_param(raw, label):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "query parameter {} must be an integer".format(label))


def parse_pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0)."""
    limit = DEFAULT_LIMIT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "limit must be between {} and {}".format(MIN_LIMIT, MAX_LIMIT),
            )
    offset = DEFAULT_OFFSET
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < DEFAULT_OFFSET:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(items, serialize):
    """Sorted by created_at ascending (insertion order tiebreak), paginated."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda entity: (entity["created_at"], entity["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize(entity) for entity in page], limit, offset, total)
