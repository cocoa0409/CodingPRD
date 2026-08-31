"""Body parsing and shape/value validation helpers (priority 6 and 7)."""
from flask import request

import store
from errors import ApiError


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


# ---------------------------------------------------------------- existence
def find(coll, rec_id, err_id):
    if not isinstance(rec_id, str):
        raise ApiError(err_id, "resource not found")
    rec = coll.get(rec_id)
    if rec is None:
        raise ApiError(err_id, "resource not found")
    return rec


def body_fk(data, field, coll, err_id, required=False):
    """Resolve a FK named in the body. Returns None when the key is absent/null."""
    if field not in data or data.get(field) is None:
        return None
    value = data.get(field)
    if not isinstance(value, str) or value not in coll:
        raise ApiError(err_id, "%s does not exist" % field)
    return coll[value]


# ---------------------------------------------------------------- scalars
def require(data, field):
    if field not in data or data.get(field) is None:
        bad("%s is required" % field)
    return data.get(field)


def as_string(data, field, required=True, min_len=None, max_len=None):
    if field not in data or data.get(field) is None:
        if required:
            bad("%s is required" % field)
        return None
    value = data.get(field)
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a non-empty string" % field)
    if min_len is not None and len(value) < min_len:
        bad("%s is too short" % field)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long" % field)
    return value


def as_enum(data, field, allowed, required=True):
    if field not in data or data.get(field) is None:
        if required:
            bad("%s is required" % field)
        return None
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def as_number(data, field, required=True, minimum=None, maximum=None,
              exclusive_min=False):
    if field not in data or data.get(field) is None:
        if required:
            bad("%s is required" % field)
        return None
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % field)
    if exclusive_min and minimum is not None and not value > minimum:
        bad("%s must be greater than %s" % (field, minimum))
    if not exclusive_min and minimum is not None and value < minimum:
        bad("%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (field, maximum))
    return value


def as_integer(data, field, required=True, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        if required:
            bad("%s is required" % field)
        return None
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (field, maximum))
    return value


def as_boolean(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    value = data.get(field)
    if not isinstance(value, bool):
        bad("%s must be a boolean" % field)
    return value


def as_date(data, field, required=True):
    if field not in data or data.get(field) is None:
        if required:
            bad("%s is required" % field)
        return None
    value = data.get(field)
    if store.parse_date(value) is None:
        bad("%s must be a YYYY-MM-DD date" % field)
    return value


def as_datetime(data, field, required=True):
    if field not in data or data.get(field) is None:
        if required:
            bad("%s is required" % field)
        return None
    value = data.get(field)
    parsed = store.parse_datetime(value)
    if parsed is None:
        bad("%s must be an ISO-8601 datetime" % field)
    return parsed


def unique(coll, field, value, scope_field=None, scope_value=None):
    for rec in coll.values():
        if rec.get(field) != value:
            continue
        if scope_field is not None and rec.get(scope_field) != scope_value:
            continue
        bad("%s must be unique" % field)
