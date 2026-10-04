"""Request-body helpers: required fields, enumerations, and typed lookups."""

from flask import request

from clock import parse_dt
from errors import APIError

# Declared enumerations (scaffold section 1.1 constraints).
ENUMS = {
    "funding_type": ("SELF_FUNDED", "FULLY_INSURED"),
    "allocation_method": ("SEQUENTIAL_BUNDLE", "CONCURRENT_BUNDLE"),
    "account_status": ("ACTIVE", "SUSPENDED"),
    "bundle_type": (
        "DIAGNOSTIC_IUI", "IVF_RETRIEVAL_TRANSFER", "PRESERVATION",
        "DONOR_EGG", "DONOR_SPERM", "SURROGACY", "MEDICATION",
    ),
    "required_track": (
        "STANDARD_IVF", "DIAGNOSTIC_IUI", "PRESERVATION",
        "DONOR_EGG", "DONOR_SPERM", "SURROGACY",
    ),
    "network_tier": ("PREFERRED", "STANDARD", "OUT_OF_NETWORK"),
    "pathway_type": ("PRESERVATION", "DONOR_EGG", "DONOR_SPERM", "SURROGACY"),
    "plan_pathway_type": (
        "STANDARD_IVF", "DIAGNOSTIC_IUI", "PRESERVATION",
        "DONOR_EGG", "DONOR_SPERM", "SURROGACY",
    ),
    "carrier_kind": ("MEMBER", "GESTATIONAL_CARRIER", "CUSTODIAN"),
    "service_category": (
        "CLINIC_BUNDLE", "MEDICATION", "LAB", "STORAGE",
        "DONOR_MATERIAL", "SURROGACY_FEE",
    ),
}


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise APIError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def require(data, name):
    if name not in data or data[name] is None:
        raise APIError("ERR_INVALID_REQUEST", "The required input '%s' is missing." % name)
    return data[name]


def opt(data, name, default=None):
    value = data.get(name)
    return default if value is None else value


def enum_of(field, value, name=None):
    allowed = ENUMS[field]
    if value not in allowed:
        raise APIError(
            "ERR_INVALID_REQUEST",
            "The value for '%s' is outside its declared enumeration." % (name or field),
        )
    return value


def require_enum(data, name, field=None):
    value = require(data, name)
    if not isinstance(value, str):
        raise APIError("ERR_INVALID_REQUEST", "The value for '%s' must be a string." % name)
    return enum_of(field or name, value, name)


def require_int(data, name):
    value = require(data, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError("ERR_INVALID_REQUEST", "The value for '%s' must be an integer." % name)
    return value


def opt_int(data, name, default=None):
    value = data.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError("ERR_INVALID_REQUEST", "The value for '%s' must be an integer." % name)
    return value


def require_dt(data, name):
    value = require(data, name)
    parsed = parse_dt(value)
    if parsed is None:
        raise APIError("ERR_INVALID_REQUEST", "The value for '%s' must be an instant." % name)
    return parsed


def opt_dt(data, name, default=None):
    value = data.get(name)
    if value is None:
        return default
    parsed = parse_dt(value)
    if parsed is None:
        raise APIError("ERR_INVALID_REQUEST", "The value for '%s' must be an instant." % name)
    return parsed