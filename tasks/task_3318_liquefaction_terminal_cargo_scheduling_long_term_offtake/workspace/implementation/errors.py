"""Error classes and response envelope helpers."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog (id -> http status)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_SPA_INVALID_STATE": 409,
    "ERR_NO_COMMERCIAL_TRAIN": 422,
    "ERR_TRAIN_INVALID_STATE": 409,
    "ERR_COMMISSIONING_INCOMPLETE": 422,
    "ERR_TURNAROUND_INVALID_STATE": 409,
    "ERR_TURNAROUND_SOD_VIOLATION": 403,
    "ERR_TURNAROUND_OVERLAP": 409,
    "ERR_ADP_INVALID_STATE": 409,
    "ERR_ACQ_EXCEEDED": 422,
    "ERR_RECONCILE_PREMATURE": 422,
    "ERR_SLOT_INVALID_STATE": 409,
    "ERR_SLOT_WINDOW_INVALID": 422,
    "ERR_INSUFFICIENT_NOTICE": 422,
    "ERR_VESSEL_BERTH_INCOMPATIBLE": 422,
    "ERR_BERTH_WINDOW_OVERLAP": 409,
    "ERR_BERTH_NOT_SERVICEABLE": 422,
    "ERR_CALL_INVALID_STATE": 409,
    "ERR_STATEMENT_INVALID_STATE": 409,
    "ERR_SCHEDULE_INVALID_STATE": 409,
    "ERR_SCHEDULE_CAPACITY_EXCEEDED": 422,
    "ERR_PIPELINE_NOT_SERVICEABLE": 422,
    "ERR_NOMINATION_QUANTITY_MISMATCH": 422,
    "ERR_NOMINATION_INVALID_STATE": 409,
    "ERR_CANCELLATION_INVALID_STATE": 409,
    "ERR_RESALE_INVALID_STATE": 409,
    "ERR_RESALE_VOLUME_EXCEEDED": 422,
}


def fail(error_id, message):
    raise ApiError(error_id, message, ERR[error_id])


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _ts_now():
    """Wall-clock timestamp for the meta envelope (3 fractional digits)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def iso_now():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": iso_now()}


def ok_object(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count, status=200):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit/offset with defaults 10/0, min 1, max 100. Bad values -> 400."""
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """items: full sorted list (ascending created_at). Returns response."""
    limit, offset = parse_pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array(page, limit, offset, total)
