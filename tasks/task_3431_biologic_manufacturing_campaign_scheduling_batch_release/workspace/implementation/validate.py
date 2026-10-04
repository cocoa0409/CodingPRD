"""Validation pipeline helpers (PRD 2.6 stage ordering).

Stage 1/2 auth: auth.require_auth. Stage 3 existence: must_* fetchers (path
ids left-to-right, then body references). Stage 4 well-formedness: body(),
req_* / opt_* field validators, pagination. Later stages live in the route
modules and calc modules.
"""
from flask import request

import clock
import store
from errors import err

# kind -> (store bucket, not-found error id)
_KIND_MAP = {
    "site": ("sites", "ERR_SITE_NOT_FOUND"),
    "product": ("products", "ERR_PRODUCT_NOT_FOUND"),
    "train": ("trains", "ERR_TRAIN_NOT_FOUND"),
    "campaign": ("campaigns", "ERR_CAMPAIGN_NOT_FOUND"),
    "seed_stage": ("seed_stages", "ERR_SEED_STAGE_NOT_FOUND"),
    "batch": ("batches", "ERR_BATCH_NOT_FOUND"),
    "test": ("tests", "ERR_TEST_NOT_FOUND"),
    "deviation": ("deviations", "ERR_DEVIATION_NOT_FOUND"),
    "shipment": ("shipments", "ERR_SHIPMENT_NOT_FOUND"),
    "material": ("materials", "ERR_MATERIAL_NOT_FOUND"),
    "inspection": ("inspections", "ERR_INSPECTION_NOT_FOUND"),
    "study": ("studies", "ERR_COMPARABILITY_STUDY_NOT_FOUND"),
}


def must_get(kind, rec_id):
    bucket, error_id = _KIND_MAP[kind]
    rec = store.get(bucket, rec_id)
    if rec is None:
        err(error_id, f"No {kind} with id {rec_id}")
    return rec


def body():
    """Request JSON body as a dict; anything else is ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_present(d, name):
    if name not in d or d[name] is None:
        err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return d[name]


def req_str(d, name):
    v = req_present(d, name)
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def opt_str(d, name):
    v = d.get(name)
    if v is not None and not isinstance(v, str):
        err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def req_enum(d, name, allowed):
    v = req_present(d, name)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", f"Field {name} must be one of {list(allowed)}")
    return v


def req_bool(d, name):
    v = req_present(d, name)
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def req_int(d, name, min_value=None):
    v = req_present(d, name)
    if not _is_int(v):
        err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if min_value is not None and v < min_value:
        err("ERR_INVALID_REQUEST", f"Field {name} must be >= {min_value}")
    return v


def req_num(d, name):
    v = req_present(d, name)
    if not _is_num(v):
        err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    return v


def req_dt(d, name):
    v = req_present(d, name)
    dt = clock.parse_dt(v)
    if dt is None:
        err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO 8601 datetime")
    return dt


def req_list(d, name, min_len=None):
    v = req_present(d, name)
    if not isinstance(v, list):
        err("ERR_INVALID_REQUEST", f"Field {name} must be an array")
    if min_len is not None and len(v) < min_len:
        err("ERR_INVALID_REQUEST", f"Field {name} must have at least {min_len} entries")
    return v


def opt_list(d, name):
    v = d.get(name)
    if v is None:
        return []
    if not isinstance(v, list):
        err("ERR_INVALID_REQUEST", f"Field {name} must be an array")
    return v


def action_value(d, field, allowed):
    """action / to_status fields: missing -> ERR_INVALID_REQUEST; unsupported
    value -> ERR_UNSUPPORTED_ACTION (PRD 2.6 stage 4)."""
    v = req_present(d, field)
    if not isinstance(v, str) or v not in allowed:
        err("ERR_UNSUPPORTED_ACTION", f"Unsupported {field}: {v}")
    return v


def pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(recs):
    """Sort by created_at asc, slice, return (page, total, limit, offset)."""
    limit, offset = pagination()
    ordered = store.sort_created(recs)
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset
