"""Request-body well-formedness helpers (PRD section 2.7 step 6)."""

from flask import request

import store
from errors import fail

MISSING = object()


def body():
    """Parse the JSON body.  A missing body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def req(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return data[name]


def req_str(data, name, allow_empty=False):
    value = req(data, name)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def opt_str(data, name, default=None, allow_empty=True):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % name)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_int(data, name, minimum=None, maximum=None):
    value = req(data, name)
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, maximum))
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    return req_int(data, name, minimum, maximum)


def req_num(data, name, minimum=None, maximum=None, exclusive_min=None):
    value = req(data, name)
    if not _is_num(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (name, exclusive_min))
    return value


def opt_num(data, name, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not _present(data, name):
        return default
    return req_num(data, name, minimum, maximum, exclusive_min)


def req_bool(data, name):
    value = req(data, name)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    return req_bool(data, name)


def req_enum(data, name, allowed):
    value = req(data, name)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_date(data, name):
    value = req_str(data, name)
    parsed = store.parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % name)
    return parsed


def opt_date(data, name, default=None):
    if not _present(data, name):
        return default
    return req_date(data, name)


def req_datetime(data, name):
    value = req_str(data, name)
    parsed = store.parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC datetime." % name)
    return parsed


def opt_datetime(data, name, default=None):
    if not _present(data, name):
        return default
    return req_datetime(data, name)


def req_enum_array(data, name, allowed, non_empty=True):
    value = req(data, name)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' contains an undeclared member." % name)
    return list(value)


def opt_enum_array(data, name, allowed, default=None):
    if not _present(data, name):
        return list(default) if default is not None else None
    return req_enum_array(data, name, allowed, non_empty=False)


def req_lines(data, name="lines"):
    value = req(data, name)
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % name)
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Every order line must be an object.")
        sku = item.get("sku")
        if not isinstance(sku, str) or sku.strip() == "":
            fail("ERR_INVALID_REQUEST", "Every order line needs a non-empty 'sku' string.")
        unit = item.get("unit_price_cents")
        if not _is_int(unit) or unit < 0:
            fail("ERR_INVALID_REQUEST",
                 "Every order line needs an integer 'unit_price_cents' of at least 0.")
        qty = item.get("quantity")
        if not _is_int(qty) or qty < 1:
            fail("ERR_INVALID_REQUEST",
                 "Every order line needs an integer 'quantity' of at least 1.")
        cleaned.append({"sku": sku, "unit_price_cents": unit, "quantity": qty})
    return cleaned


def req_mmdd(data, name):
    value = req_str(data, name)
    if not store.valid_mmdd(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an MM-DD string." % name)
    return value


def opt_mmdd(data, name, default=None):
    if not _present(data, name):
        return default
    return req_mmdd(data, name)


def req_id(data, name):
    value = req(data, name)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty identifier." % name)
    return value


def opt_id(data, name, default=None):
    if not _present(data, name):
        return default
    return req_id(data, name)


def is_multiple_of_quarter(value):
    return abs(round(value * 4) - value * 4) < 1e-9
