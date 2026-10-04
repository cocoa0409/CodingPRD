"""Request-body shape checks and §2.3 pagination."""

from flask import request

import common
import store
from common import ApiError


ENUM_MEMBERS = {
    "service_region": common.REGIONS,
    "region": common.REGIONS,
    "category": common.CATEGORIES,
    "procurement_grade": common.PROCUREMENT_GRADES,
    "insulation_profile": common.INSULATION_PROFILES,
    "cuisine_preference": common.CUISINE_PREFERENCES,
    "cadence": common.CADENCES,
    "cancellation_reason": common.CANCELLATION_REASONS,
    "reason_code": common.CLAIM_REASON_CODES,
    "outcome": common.CLAIM_OUTCOMES,
    "quality_outcome": ("PASS", "REJECTED"),
    "status": None,
}


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "The request body must be a JSON object.")
    return data


def missing(data, required):
    absent = [name for name in required if data.get(name) is None]
    if absent:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "Missing required field(s): " + ", ".join(absent) + ".",
        )


def reject_unknown(data, allowed):
    """§1.2 / §5: a field the endpoint does not declare is a malformed request."""
    extra = [name for name in data if name not in allowed]
    if extra:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "Unknown field(s): " + ", ".join(sorted(extra)) + ".",
        )


def check_enum(field, value, members):
    if value is None:
        return
    if value not in members:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "Field %s is not a declared enum member." % field,
        )


def check_barcode(value):
    if value is None:
        return
    text = str(value)
    if len(text) != 14 or not text.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "barcode_gtin must be exactly 14 digits.")


def as_int(field, value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer." % field)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer." % field)


def as_string_list(field, value):
    """Arrays are stored sorted ascending and compared on that form (§3.1)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field %s must be an array." % field)
    return sorted(str(v) for v in value)


def pagination_args():
    """§2.3 limit/offset with defaults, min 1 and max 100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = common.PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer.")
        if limit < common.PAGINATION_MIN_LIMIT or limit > common.PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "limit must be between 1 and 100.")
    if raw_offset is None:
        offset = common.PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    """Rows are returned oldest-created first, per §2.3."""
    ordered = store.by_created(rows)
    return ordered[offset:offset + limit]


def query_filter(rows, field):
    value = request.args.get(field)
    if value is None or value == "":
        return rows
    return [r for r in rows if str(r.get(field)) == value]


def query_filter_bool(rows, field):
    value = request.args.get(field)
    if value is None or value == "":
        return rows
    wanted = str(value).lower() in ("true", "1", "yes")
    return [r for r in rows if bool(r.get(field)) is wanted]