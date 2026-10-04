"""Error catalogue, response envelope and request-time helpers."""

import random
import string
from flask import jsonify, request

from db import DB, iso


# ---------------------------------------------------------------------------
# Error ids, exactly as the catalogue declares them
# ---------------------------------------------------------------------------
class Err(object):
    UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    UNAUTHORIZED = "ERR_UNAUTHORIZED"
    INVALID_REQUEST = "ERR_INVALID_REQUEST"
    VALIDATION_FAILED = "ERR_VALIDATION_FAILED"
    RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
    DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"
    DUPLICATE_STONE_CODE = "ERR_DUPLICATE_STONE_CODE"
    REGISTRY_ROW_MISSING = "ERR_REGISTRY_ROW_MISSING"
    CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
    DOWN_PAYMENT_REQUIRED = "ERR_DOWN_PAYMENT_REQUIRED"
    CREDIT_FROZEN = "ERR_CREDIT_FROZEN"
    ACCOUNT_NOT_OPEN = "ERR_ACCOUNT_NOT_OPEN"
    INVALID_STATE = "ERR_INVALID_STATE"
    NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
    STALE_VERSION = "ERR_STALE_VERSION"
    PLAN_ALREADY_EXISTS = "ERR_PLAN_ALREADY_EXISTS"
    INSUFFICIENT_PAYOFF = "ERR_INSUFFICIENT_PAYOFF"
    WINDOW_EXPIRED = "ERR_WINDOW_EXPIRED"
    EXTENSION_WINDOW_EXPIRED = "ERR_EXTENSION_WINDOW_EXPIRED"
    HOLD_PROMISE_CEILING = "ERR_HOLD_PROMISE_CEILING"
    REGULATION_TERMS_VIOLATION = "ERR_REGULATION_TERMS_VIOLATION"
    PLAN_TERM_EXCEEDS_REGULATION = "ERR_PLAN_TERM_EXCEEDS_REGULATION"
    PLAN_TERMS_UNSATISFIED = "ERR_PLAN_TERMS_UNSATISFIED"
    REGISTRATION_TERMINATED = "ERR_REGISTRATION_TERMINATED"
    ORIGIN_DOCUMENT_MISSING = "ERR_ORIGIN_DOCUMENT_MISSING"
    RING_METAL_NOT_CERTIFIED = "ERR_RING_METAL_NOT_CERTIFIED"
    INSUFFICIENT_DEPOSIT = "ERR_INSUFFICIENT_DEPOSIT"
    REVISION_LIMIT_REACHED = "ERR_REVISION_LIMIT_REACHED"
    VENDOR_MISSING = "ERR_VENDOR_MISSING"
    VENDOR_AGREEMENT_REQUIRED = "ERR_VENDOR_AGREEMENT_REQUIRED"
    APPRAISAL_REQUIRED = "ERR_APPRAISAL_REQUIRED"
    CLAIM_ALREADY_USED = "ERR_CLAIM_ALREADY_USED"
    TRADE_UP_GUARDIAN_REFERENCE = "ERR_TRADE_UP_GUARDIAN_REFERENCE"
    TRADE_UP_FLOOR_NOT_MET = "ERR_TRADE_UP_FLOOR_NOT_MET"
    STORE_CREDIT_CAPACITY_EXCEEDED = "ERR_STORE_CREDIT_CAPACITY_EXCEEDED"
    CUSTOMER_ACTIVE_OBLIGATIONS = "ERR_CUSTOMER_ACTIVE_OBLIGATIONS"
    STATEMENT_OVERPAYMENT = "ERR_STATEMENT_OVERPAYMENT"


HTTP_STATUS = {
    Err.UNAUTHENTICATED: 401,
    Err.UNAUTHORIZED: 403,
    Err.INVALID_REQUEST: 400,
    Err.VALIDATION_FAILED: 422,
    Err.RESOURCE_NOT_FOUND: 404,
    Err.DUPLICATE_EMAIL: 409,
    Err.DUPLICATE_STONE_CODE: 409,
    Err.REGISTRY_ROW_MISSING: 422,
    Err.CREDIT_LIMIT_EXCEEDED: 422,
    Err.DOWN_PAYMENT_REQUIRED: 422,
    Err.CREDIT_FROZEN: 422,
    Err.ACCOUNT_NOT_OPEN: 422,
    Err.INVALID_STATE: 409,
    Err.NOT_RESOURCE_OWNER: 403,
    Err.STALE_VERSION: 412,
    Err.PLAN_ALREADY_EXISTS: 409,
    Err.INSUFFICIENT_PAYOFF: 422,
    Err.WINDOW_EXPIRED: 422,
    Err.EXTENSION_WINDOW_EXPIRED: 422,
    Err.HOLD_PROMISE_CEILING: 422,
    Err.REGULATION_TERMS_VIOLATION: 422,
    Err.PLAN_TERM_EXCEEDS_REGULATION: 422,
    Err.PLAN_TERMS_UNSATISFIED: 422,
    Err.REGISTRATION_TERMINATED: 409,
    Err.ORIGIN_DOCUMENT_MISSING: 422,
    Err.RING_METAL_NOT_CERTIFIED: 422,
    Err.INSUFFICIENT_DEPOSIT: 422,
    Err.REVISION_LIMIT_REACHED: 409,
    Err.VENDOR_MISSING: 422,
    Err.VENDOR_AGREEMENT_REQUIRED: 422,
    Err.APPRAISAL_REQUIRED: 422,
    Err.CLAIM_ALREADY_USED: 409,
    Err.TRADE_UP_GUARDIAN_REFERENCE: 409,
    Err.TRADE_UP_FLOOR_NOT_MET: 422,
    Err.STORE_CREDIT_CAPACITY_EXCEEDED: 422,
    Err.CUSTOMER_ACTIVE_OBLIGATIONS: 409,
    Err.STATEMENT_OVERPAYMENT: 422,
}

MESSAGES = {
    Err.UNAUTHENTICATED: "X-User-Role and X-User-ID headers are required and X-User-Role must name a declared role.",
    Err.UNAUTHORIZED: "The acting role is not permitted to perform this operation.",
    Err.INVALID_REQUEST: "The request body is malformed.",
    Err.VALIDATION_FAILED: "A field carries a value outside its declared constraint set.",
    Err.RESOURCE_NOT_FOUND: "The named resource does not exist.",
    Err.DUPLICATE_EMAIL: "Another customer already holds this email address.",
    Err.DUPLICATE_STONE_CODE: "The supplied code is already on file.",
    Err.REGISTRY_ROW_MISSING: "No risk-registry row resolves for the priced tier and requested amount.",
    Err.CREDIT_LIMIT_EXCEEDED: "The requested credit exceeds the standalone limit implied by the credit tier.",
    Err.DOWN_PAYMENT_REQUIRED: "The declared down payment is below the formula-derived minimum.",
    Err.CREDIT_FROZEN: "Credit is frozen while a promotional plan of this customer is DEFAULTED.",
    Err.ACCOUNT_NOT_OPEN: "The customer account carrying this obligation is not OPEN.",
    Err.INVALID_STATE: "The resource is not in a state from which this transition is declared.",
    Err.NOT_RESOURCE_OWNER: "The acting customer does not own the named resource.",
    Err.STALE_VERSION: "The asserted version no longer matches the resource's current version.",
    Err.PLAN_ALREADY_EXISTS: "A non-terminal promotional plan already references this purchase.",
    Err.INSUFFICIENT_PAYOFF: "The payoff amount is below the plan's final settlement amount.",
    Err.WINDOW_EXPIRED: "The acting instant falls outside the resource's declared validity window.",
    Err.EXTENSION_WINDOW_EXPIRED: "The visit instant is earlier than the registration's current inspection due instant.",
    Err.HOLD_PROMISE_CEILING: "The requested extension would push the promise past the ceiling.",
    Err.REGULATION_TERMS_VIOLATION: "The governing lifetime-plan regulation terms are not satisfied.",
    Err.PLAN_TERM_EXCEEDS_REGULATION: "The plan term exceeds the maximum the state permits.",
    Err.PLAN_TERMS_UNSATISFIED: "The pinned lifetime plan no longer covers this repair.",
    Err.REGISTRATION_TERMINATED: "The registration is already in a terminal coverage status.",
    Err.ORIGIN_DOCUMENT_MISSING: "A natural centre stone over 1.00 carat requires an origin document on file.",
    Err.RING_METAL_NOT_CERTIFIED: "The named alloy is not a certified production metal.",
    Err.INSUFFICIENT_DEPOSIT: "The deposit percentage falls below the permitted floor.",
    Err.REVISION_LIMIT_REACHED: "At most five CAD revisions may be requested on one commission.",
    Err.VENDOR_MISSING: "The bench shop named by the routing rule does not exist with vendor_status ACTIVE.",
    Err.VENDOR_AGREEMENT_REQUIRED: "The rush routing shop holds no signed alliance agreement.",
    Err.APPRAISAL_REQUIRED: "The repair file carries no issued replacement appraisal.",
    Err.CLAIM_ALREADY_USED: "This registration's replacement claim has already been used.",
    Err.TRADE_UP_GUARDIAN_REFERENCE: "A trade-up credit may only be stamped on the leader of its console.",
    Err.TRADE_UP_FLOOR_NOT_MET: "The ticket does not reach twice the origin purchase price.",
    Err.STORE_CREDIT_CAPACITY_EXCEEDED: "The store's available credit capacity cannot cover this obligation.",
    Err.CUSTOMER_ACTIVE_OBLIGATIONS: "The customer still carries a live obligation.",
    Err.STATEMENT_OVERPAYMENT: "The payment exceeds the sum of the three bucket balances.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        Exception.__init__(self, error_id)
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)


def bad_request(message=None):
    return ApiError(Err.INVALID_REQUEST, message)


def not_found(message=None):
    return ApiError(Err.RESOURCE_NOT_FOUND, message)


def invalid_state(message=None):
    return ApiError(Err.INVALID_STATE, message)


def validation_failed(message=None):
    return ApiError(Err.VALIDATION_FAILED, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def success(data, response_type, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(DB.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data})


def ok_obj(data):
    return success(data, "object"), 200


def created_obj(data):
    return success(data, "object"), 201


def ok_list(rows, limit, offset, total):
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success(page, "array", pagination), 200


def error_response(err):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(DB.now()),
    }
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("The request body must be a JSON object.")
    return data


PRIMITIVES = (str, int, float, bool, list, dict)


def ensure_known(data, allowed, optional=()):
    """Reject unknown keys and missing required keys.

    `allowed` carries the declared input field names; `optional` names the ones
    that may be omitted.
    """
    for key in data:
        if key not in allowed:
            raise bad_request("Unknown field %s." % key)
    for key in allowed:
        if key in optional:
            continue
        if key not in data or data[key] is None:
            raise bad_request("Field %s is required." % key)


def as_str(data, key, required=True):
    value = data.get(key)
    if value is None:
        if required:
            raise bad_request("Field %s is required." % key)
        return None
    if not isinstance(value, str):
        raise bad_request("Field %s must be a string." % key)
    return value


def as_int(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field %s must be an integer." % key)
    if isinstance(value, float) and value != int(value):
        raise bad_request("Field %s must be an integer." % key)
    return int(value)


def as_num(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field %s must be a number." % key)
    return float(value)


def as_bool(data, key, default=False, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    if not isinstance(value, bool):
        raise bad_request("Field %s must be a boolean." % key)
    return value


def as_enum(data, key, allowed, default=None, required=True):
    value = data.get(key)
    if value is None:
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    if not isinstance(value, str) or value not in allowed:
        raise validation_failed("Field %s is outside its constraint set." % key)
    return value


def as_instant(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise bad_request("Field %s is required." % key)
        return default
    from db import parse_dt
    dt = parse_dt(value)
    if dt is None:
        raise bad_request("Field %s must be an ISO 8601 instant." % key)
    return dt


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("limit must fall between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer.")
        if offset < 0:
            raise bad_request("offset must not be negative.")
    return limit, offset


def sorted_by_created(rows):
    rows = list(rows)
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    return rows