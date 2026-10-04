"""Stage-3 request-schema helpers (PRD 2.8): required fields, types, enums,
unknown-key rejection, conditional requiredness primitives."""
import json

from flask import request

import clock
from errors import err

MISSING = object()


def parse_body():
    """Return the JSON object body; {} when absent. Malformed/non-object -> 400."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def reject_unknown(data, allowed_keys):
    extra = [k for k in data.keys() if k not in allowed_keys]
    if extra:
        err("ERR_INVALID_REQUEST", "Unknown field(s): %s." % ", ".join(sorted(extra)))


def field(data, key, required=False):
    value = data.get(key, MISSING)
    if value is MISSING or value is None:
        if required:
            err("ERR_INVALID_REQUEST", "Missing required field: %s." % key)
        return None
    return value


def as_str(data, key, required=False):
    value = field(data, key, required)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % key)
    return value


def as_int(data, key, required=False, minimum=None):
    value = field(data, key, required)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_INVALID_REQUEST", "Field %s must be an integer." % key)
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (key, minimum))
    return value


def as_num(data, key, required=False, minimum=None, exclusive_minimum=False):
    value = field(data, key, required)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        err("ERR_INVALID_REQUEST", "Field %s must be a number." % key)
    if minimum is not None:
        if exclusive_minimum and not value > minimum:
            err("ERR_INVALID_REQUEST", "Field %s must be > %s." % (key, minimum))
        if not exclusive_minimum and value < minimum:
            err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (key, minimum))
    return value


def as_bool(data, key, required=False):
    value = field(data, key, required)
    if value is None:
        return None
    if not isinstance(value, bool):
        err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % key)
    return value


def as_list(data, key, required=False):
    value = field(data, key, required)
    if value is None:
        return None
    if not isinstance(value, list):
        err("ERR_INVALID_REQUEST", "Field %s must be an array." % key)
    return value


def as_dict(data, key, required=False):
    value = field(data, key, required)
    if value is None:
        return None
    if not isinstance(value, dict):
        err("ERR_INVALID_REQUEST", "Field %s must be an object." % key)
    return value


def as_enum(data, key, domain, required=False):
    value = field(data, key, required)
    if value is None:
        return None
    if value not in domain:
        err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (key, ", ".join(domain)))
    return value


def as_datetime(data, key, required=False):
    value = field(data, key, required)
    if value is None:
        return None
    dt = clock.parse(value)
    if dt is None:
        err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 UTC timestamp." % key)
    return dt


USE_SITE_KEYS = [
    "site_code",
    "pest_code",
    "max_application_rate_lbs_acre",
    "max_applications_per_season",
    "preharvest_interval_days",
    "application_method",
    "restricted_entry_interval_hours",
]


def validate_use_site(value):
    """Validate a use-site object's schema (PRD 3.2). The 8.0 lbs/acre safety cap
    is NOT checked here — it is a stage-8 business-safety rule checked later."""
    import constants  # local import to keep module import order simple

    if not isinstance(value, dict):
        err("ERR_INVALID_REQUEST", "Each use site must be an object.")
    reject_unknown(value, USE_SITE_KEYS)
    site = {
        "site_code": as_str(value, "site_code", required=True),
        "pest_code": as_str(value, "pest_code", required=True),
        "max_application_rate_lbs_acre": as_num(
            value, "max_application_rate_lbs_acre", required=True, minimum=0, exclusive_minimum=True
        ),
        "max_applications_per_season": as_int(
            value, "max_applications_per_season", required=True, minimum=1
        ),
        "preharvest_interval_days": as_int(
            value, "preharvest_interval_days", required=True, minimum=0
        ),
        "application_method": as_enum(
            value, "application_method", constants.APPLICATION_METHODS, required=True
        ),
        "restricted_entry_interval_hours": as_int(
            value, "restricted_entry_interval_hours", required=True, minimum=0
        ),
    }
    return site


def parse_pagination():
    """limit/offset query params (PRD 2.3); out-of-range values clamp to bounds."""
    import constants

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = constants.PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = max(constants.PAGINATION_MIN_LIMIT, min(constants.PAGINATION_MAX_LIMIT, limit))
    if raw_offset is None:
        offset = constants.PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = max(0, offset)
    return limit, offset


def paginate(rows):
    """Sort (created_at asc), slice, and return (page, limit, offset, total)."""
    from db import sorted_rows

    limit, offset = parse_pagination()
    ordered = sorted_rows(rows)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, limit, offset, total
