"""Request-body and query-parameter validation helpers (priority-0 checks)."""
from flask import request

from errors import bad_request

SUBJECTS = ("MATH", "SCIENCE", "LITERACY", "ARTS", "SOCIAL_STUDIES", "HEALTH_PE", "OTHER")
GRADE_BANDS = ("K_2", "G3_5", "G6_8", "G9_12")
CATEGORIES = ("BOOKS", "TECHNOLOGY", "FURNITURE", "SUPPLIES", "LAB_EQUIPMENT", "SPORTS")
SHIPPING_ZONES = ("A", "B", "C")
TARGET_TYPES = ("SCHOOL", "SUBJECT", "STATE")


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def require_present(data, field):
    if field not in data or data[field] is None:
        raise bad_request("Missing required field: %s" % field)
    return data[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise bad_request("Field %s must be a non-empty string" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field %s must be an integer" % field)
    return value


def as_num(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field %s must be a number" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise bad_request("Field %s must be a boolean" % field)
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field %s must be one of %s" % (field, ", ".join(allowed)))
    return value


def as_subject_list(value, field):
    if not isinstance(value, list):
        raise bad_request("Field %s must be an array" % field)
    for element in value:
        if not isinstance(element, str) or element not in SUBJECTS:
            raise bad_request("Field %s must contain only subject values" % field)
    return list(value)


def optional_int(data, field, minimum=None):
    """Optional integer field; explicit null is accepted as None."""
    if field not in data or data[field] is None:
        return None
    value = as_int(data[field], field)
    if minimum is not None and value < minimum:
        raise bad_request("Field %s must be at least %d" % (field, minimum))
    return value


def optional_bool(data, field):
    if field not in data or data[field] is None:
        return None
    return as_bool(data[field], field)


def optional_str(data, field):
    if field not in data or data[field] is None:
        return None
    return as_str(data[field], field)


def pagination_args():
    """limit: default 10, clamped to [1, 100]; offset: default 0, clamped >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise bad_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise bad_request("offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
