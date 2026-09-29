"""§2.2 response envelope, §5 error catalogue and §2.3 pagination."""

from datetime import datetime, timezone

from flask import jsonify

from core import request_id

# §5 Error Code Catalogue — 48 codes.
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_LOCAL_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_LIST_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_JOB_REQUEST_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_DISPATCH_NOT_FOUND": 404,
    "ERR_GRIEVANCE_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_JOB_REQUEST_SUSPENDED": 409,
    "ERR_JOB_REQUEST_NOT_OPEN": 409,
    "ERR_REFERRAL_NOT_PENDING": 409,
    "ERR_REGISTRATION_NOT_ACTIVE": 409,
    "ERR_DISPATCH_NOT_WORKING": 409,
    "ERR_RECALL_NOT_ELIGIBLE": 409,
    "ERR_GRIEVANCE_NOT_UNDER_REVIEW": 409,
    "ERR_STALE_JOB_REQUEST_VERSION": 412,
    "ERR_CONTRACTOR_NOT_SIGNATORY": 409,
    "ERR_MEMBER_NOT_IN_GOOD_STANDING": 409,
    "ERR_CLASSIFICATION_MISMATCH": 422,
    "ERR_SKILL_ENDORSEMENT_MISSING": 409,
    "ERR_LIST_GROUP_NOT_ELIGIBLE": 422,
    "ERR_TRAVELER_NOT_RECIPROCAL": 409,
    "ERR_REREGISTRATION_PREDECESSOR_MISMATCH": 422,
    "ERR_NAMED_CALL_NOT_DECLARED": 409,
    "ERR_DISPATCH_RECORD_PURGED": 409,
    "ERR_REREGISTRATION_TOO_EARLY": 409,
    "ERR_REREGISTRATION_WINDOW_EXPIRED": 409,
    "ERR_ACCEPTANCE_WINDOW_CLOSED": 409,
    "ERR_RECALL_WINDOW_CLOSED": 409,
    "ERR_GRIEVANCE_WINDOW_EXPIRED": 409,
    "ERR_REFERRAL_ALREADY_OUTSTANDING": 409,
    "ERR_OVERLAPPING_DISPATCH": 409,
    "ERR_MEMBER_ALREADY_REGISTERED": 409,
    "ERR_NAMED_CALL_ALLOWANCE_EXCEEDED": 409,
    "ERR_SPECIAL_SKILL_ALLOWANCE_EXCEEDED": 409,
    "ERR_NO_ACTIVE_RATIO_POLICY": 409,
    "ERR_APPRENTICE_RATIO_EXCEEDED": 409,
    "ERR_OUT_OF_ORDER_DISPATCH": 409,
    "ERR_NO_ELIGIBLE_REGISTRANT": 409,
    "ERR_HOURS_EXCEED_ELAPSED": 422,
    "ERR_REMEDY_NOT_APPLICABLE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)


def _wall_now():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": _wall_now()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, meta_extra, status=200):
    meta = _meta()
    meta.update(meta_extra)
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_HTTP.get(error_id, 400)
