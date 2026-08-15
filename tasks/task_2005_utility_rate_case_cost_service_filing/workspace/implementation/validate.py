"""Request-body shape validation (priority 0) and resource loaders (priority 5)."""
from datetime import datetime

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_RATE_CASE_NOT_FOUND,
    ERR_INTERVENOR_NOT_FOUND,
    ERR_ENTRY_NOT_FOUND,
    ERR_ADJUSTMENT_NOT_FOUND,
    ERR_ITEM_NOT_FOUND,
    ERR_CLASS_NOT_FOUND,
    ERR_DATA_REQUEST_NOT_FOUND,
    ERR_PROPOSAL_NOT_FOUND,
    ERR_SIGNATORY_NOT_FOUND,
    ERR_ASSET_NOT_FOUND,
    ERR_AMORT_ENTRY_NOT_FOUND,
    ERR_TARIFF_NOT_FOUND,
    ERR_FILING_NOT_FOUND,
)

NOT_FOUND_FOR = {
    "rate_cases": ERR_RATE_CASE_NOT_FOUND,
    "intervenors": ERR_INTERVENOR_NOT_FOUND,
    "test_year_entries": ERR_ENTRY_NOT_FOUND,
    "adjustments": ERR_ADJUSTMENT_NOT_FOUND,
    "rate_base_items": ERR_ITEM_NOT_FOUND,
    "customer_classes": ERR_CLASS_NOT_FOUND,
    "data_requests": ERR_DATA_REQUEST_NOT_FOUND,
    "settlement_proposals": ERR_PROPOSAL_NOT_FOUND,
    "settlement_signatories": ERR_SIGNATORY_NOT_FOUND,
    "regulatory_assets": ERR_ASSET_NOT_FOUND,
    "amortization_entries": ERR_AMORT_ENTRY_NOT_FOUND,
    "tariff_rates": ERR_TARIFF_NOT_FOUND,
    "compliance_filings": ERR_FILING_NOT_FOUND,
}


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def no_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"unknown field: {key}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None, positive=False, non_negative=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def _validate_datetime(v, field):
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")


def req_datetime(body, field):
    v = req_str(body, field)
    _validate_datetime(v, field)
    return v


def opt_nullable_datetime(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    _validate_datetime(v, field)
    return v


def req_str_list(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid array field: {field}")
    for item in v:
        if not isinstance(item, str):
            raise_error(ERR_INVALID_REQUEST, f"field {field} must be an array of strings")
    return list(v)


def req_tiers(body, field):
    """Tier array: ascending up_to_kwh, exactly one terminal null, integer mills."""
    v = body.get(field)
    if v is None or not isinstance(v, list) or len(v) == 0:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid tier array: {field}")
    nulls = 0
    prev_cap = None
    for i, tier in enumerate(v):
        if not isinstance(tier, dict):
            raise_error(ERR_INVALID_REQUEST, f"tier {i} must be an object")
        for key in tier:
            if key not in ("up_to_kwh", "rate_mills"):
                raise_error(ERR_INVALID_REQUEST, f"tier {i} has unknown field: {key}")
        if "up_to_kwh" not in tier or "rate_mills" not in tier:
            raise_error(ERR_INVALID_REQUEST, f"tier {i} requires up_to_kwh and rate_mills")
        cap = tier["up_to_kwh"]
        mills = tier["rate_mills"]
        if mills is None or isinstance(mills, bool) or not isinstance(mills, int) or mills < 0:
            raise_error(ERR_INVALID_REQUEST, f"tier {i} rate_mills must be a non-negative integer")
        if cap is None:
            nulls += 1
            if i != len(v) - 1:
                raise_error(ERR_INVALID_REQUEST, "the null up_to_kwh tier must be the terminal tier")
        else:
            if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
                raise_error(ERR_INVALID_REQUEST, f"tier {i} up_to_kwh must be a positive integer or null")
            if prev_cap is not None and cap <= prev_cap:
                raise_error(ERR_INVALID_REQUEST, "tiers must be ascending by up_to_kwh")
            prev_cap = cap
    if nulls != 1:
        raise_error(ERR_INVALID_REQUEST, "exactly one terminal tier must have up_to_kwh null")
    return [{"up_to_kwh": t["up_to_kwh"], "rate_mills": t["rate_mills"]} for t in v]


def require_path_resource(collection, rid):
    """Priority 5: path-parameter existence with the resource-specific 404."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(NOT_FOUND_FOR[collection], f"{collection} id not found: {rid}")
    return obj


def require_fk(collection, rid, field):
    """Priority 5: body-supplied foreign key existence."""
    if rid is None:
        return None
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(NOT_FOUND_FOR[collection], f"{field} does not resolve: {rid}")
    return obj
