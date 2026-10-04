"""Shared validation + lookup helpers implementing the §1.4 priority order."""
from flask import request

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from store import DB

# path prefix -> (store key, param name); checked in path order
_PATH_SEGMENTS = {
    "dcas": "dca",
    "sars": "sar",
    "rais": "rai",
    "test-programs": "test_program",
    "test-results": "test_result",
    "vendors": "vendor",
    "qualifications": "vendor_qualification",
    "component-lots": "component_lot",
    "site-permits": "site_permit",
    "public-hearings": "public_hearing",
    "subscriptions": "subscription",
    "cost-share-agreements": "cost_share_agreement",
    "workforce-pipelines": "workforce_pipeline",
    "operator-licenses": "operator_license",
}


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError(ERR_VALIDATION, 400, "request body must be a JSON object")
    return body


def not_found(msg="resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def get_or_404(kind, rid, msg=None):
    rec = DB[kind].get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, msg or f"{kind} {rid} not found")
    return rec


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {n}")


def v_int(body, name, required=True, minimum=None, maximum=None, exclusive_min=False):
    from store import as_int
    val = body.get(name)
    if val is None:
        if required:
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {name}")
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be an integer")
    if minimum is not None:
        if exclusive_min and not (val > minimum):
            raise ApiError(ERR_VALIDATION, 400, f"field {name} must be > {minimum}")
        if not exclusive_min and val < minimum:
            raise ApiError(ERR_VALIDATION, 400, f"field {name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be <= {maximum}")
    return val


def v_num(body, name, required=True, minimum=None, maximum=None, exclusive_min=False):
    val = body.get(name)
    if val is None:
        if required:
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {name}")
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be a number")
    if minimum is not None:
        if exclusive_min and not (val > minimum):
            raise ApiError(ERR_VALIDATION, 400, f"field {name} must be > {minimum}")
        if not exclusive_min and val < minimum:
            raise ApiError(ERR_VALIDATION, 400, f"field {name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be <= {maximum}")
    return val


def v_str(body, name, required=True):
    val = body.get(name)
    if val is None:
        if required:
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {name}")
        return None
    if not isinstance(val, str):
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be a string")
    return val


def v_bool(body, name, required=False, default=None):
    val = body.get(name)
    if val is None:
        if required:
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {name}")
        return default
    if not isinstance(val, bool):
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be a boolean")
    return val


def v_enum(body, name, choices, required=True):
    val = v_str(body, name, required=required)
    if val is None:
        return None
    if val not in choices:
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be one of {sorted(choices)}")
    return val


def v_iso(body, name, required=True):
    from store import parse_iso
    val = body.get(name)
    if val is None:
        if required:
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {name}")
        return None
    try:
        return parse_iso(val)
    except Exception:
        raise ApiError(ERR_VALIDATION, 400, f"field {name} must be an ISO8601 timestamp")
