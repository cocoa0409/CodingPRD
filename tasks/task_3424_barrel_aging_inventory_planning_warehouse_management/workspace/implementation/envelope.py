"""Response envelope helpers and the API error type.

Envelope shapes (fixed by spec):
  success: {"meta": {api_request_id, api_request_timestamp[, pagination...]},
            "response_type": "object" | "array", "data": ...}
  error:   {"meta": {api_request_id, api_request_timestamp},
            "response_type": "error", "data": {"error_id": ..., "message": ...}}
"""

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


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def ok_object(payload, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": payload}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Error constructors (exact catalog ids / statuses)
# ---------------------------------------------------------------------------

def err_unauthenticated(msg="Authentication required"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden_role(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def err_validation(msg="Request payload failed validation"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg="Invalid state transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg, 409)


def err_rickhouse_not_operating(msg="Rickhouse posture is not OPERATING"):
    return ApiError("ERR_RICKHOUSE_NOT_OPERATING", msg, 409)


def err_construction_lag(msg="Construction lag has not fully elapsed"):
    return ApiError("ERR_CONSTRUCTION_LAG_NOT_ELAPSED", msg, 409)


def err_stale_blend_batch(msg="Stale blend batch version"):
    return ApiError("ERR_STALE_BLEND_BATCH_VERSION", msg, 412)


def err_stale_program(msg="Stale program version"):
    return ApiError("ERR_STALE_PROGRAM_VERSION", msg, 412)


def err_stale_barrel(msg="Stale barrel version"):
    return ApiError("ERR_STALE_BARREL_VERSION", msg, 412)


def err_label_not_active(msg="Label is not ACTIVE"):
    return ApiError("ERR_LABEL_NOT_ACTIVE", msg, 409)


def err_age_statement(msg="Component barrel age violates the label age statement"):
    return ApiError("ERR_AGE_STATEMENT_VIOLATION", msg, 422)


def err_covering_report(msg="No FILED or ACCEPTED bonded report covers the current instant"):
    return ApiError("ERR_COVERING_REPORT_NOT_FILED", msg, 409)


def err_period_overlap(msg="Report period overlaps an existing non-REJECTED report"):
    return ApiError("ERR_REPORT_PERIOD_OVERLAP", msg, 409)


def err_segregation(msg="Accept/reject actor must differ from the filer"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_slot_overlap(msg="Slot has an overlapping OPEN occupancy"):
    return ApiError("ERR_SLOT_OCCUPANCY_OVERLAP", msg, 409)


def err_sample_buffer(msg="Quality sample recorded fewer than 30 days after the previous one"):
    return ApiError("ERR_SAMPLE_BUFFER_VIOLATION", msg, 409)


def err_quota(msg="Program reservation quota exhausted"):
    return ApiError("ERR_RESERVATION_QUOTA_EXHAUSTED", msg, 409)


def err_barrel_not_eligible(msg="Barrel fails the eligibility predicate"):
    return ApiError("ERR_BARREL_NOT_ELIGIBLE", msg, 422)


def err_duplicate_component(msg="Barrel is already a component of this batch"):
    return ApiError("ERR_DUPLICATE_BLEND_COMPONENT", msg, 409)


def err_barrel_reserved(msg="Barrel has an ACTIVE reservation"):
    return ApiError("ERR_BARREL_RESERVED", msg, 409)


def err_barrel_in_committed_blend(msg="Barrel belongs to a COMMITTED blend batch"):
    return ApiError("ERR_BARREL_IN_COMMITTED_BLEND", msg, 409)


def err_insufficient_volume(msg="Drawn volume exceeds the barrel's current ledger volume"):
    return ApiError("ERR_INSUFFICIENT_VOLUME", msg, 422)


def err_assessment_inconsistent(msg="Measured volume exceeds the barrel's current ledger volume"):
    return ApiError("ERR_ASSESSMENT_VOLUME_INCONSISTENT", msg, 422)


def err_clock_regression(msg="Clock may not be set backwards"):
    return ApiError("ERR_CLOCK_REGRESSION", msg, 422)
