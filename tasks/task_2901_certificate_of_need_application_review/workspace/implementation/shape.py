"""Body-shape validation (order-of-evaluation rank 3) and pagination parsing."""

from flask import request

import clock
from envelope import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT
from errors import ApiError

MISSING = object()

SERVICE_TYPES = (
    "ACUTE_CARE_BEDS", "NURSING_HOME_BEDS", "PSYCHIATRIC_BEDS", "MRI_UNIT",
    "OPEN_HEART_SURGERY",
)


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def req(data, key):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    return data[key]


def string_field(data, key, required=True, default=None, allow_empty=False):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must be a non-empty string." % key)
    return value


def int_field(data, key, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be an integer." % key)
    if isinstance(value, float):
        if not float(value).is_integer():
            bad("Field '%s' must be an integer." % key)
        value = int(value)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return int(value)


def number_field(data, key, required=True, default=None, minimum=None, maximum=None,
                 exclusive_min=None, exclusive_max=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        bad("Field '%s' must be > %s." % (key, exclusive_min))
    if exclusive_max is not None and value >= exclusive_max:
        bad("Field '%s' must be < %s." % (key, exclusive_max))
    return value


def bool_field(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def enum_field(data, key, allowed, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def instant_field(data, key, required=True, default=None):
    """Returns (raw_string, parsed_datetime); the raw string is stored verbatim."""
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default, None
    value = data[key]
    parsed = clock.parse_instant(value) if isinstance(value, str) else None
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 instant." % key)
    return value, parsed


def date_field(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if clock.parse_date(value) is None:
        bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return value


def array_field(data, key, required=True, default=None, non_empty=False):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return list(default) if default is not None else default
    value = data[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    if non_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % key)
    return value


HSA_CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


def hsa_code_field(data, key):
    value = string_field(data, key)
    if not (1 <= len(value) <= 16) or any(ch not in HSA_CODE_CHARS for ch in value):
        bad("Field '%s' must be 1-16 uppercase letters, digits or hyphens." % key)
    return value


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad("Query parameter 'limit' must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX))
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def filters(*names):
    """Exact-match, conjunctive collection filters from the query string."""
    picked = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            picked[name] = value
    return picked


def apply_filters(records, picked):
    result = records
    for key, value in picked.items():
        result = [r for r in result if r.get(key) == value]
    return result
