"""Existence resolution (rungs 4-5) and schema validation (rung 6)."""

from decimal import Decimal, InvalidOperation

import store
from errors import ApiError

NOT_FOUND = {
    "donors": "ERR_DONOR_NOT_FOUND",
    "serology_panels": "ERR_SEROLOGY_PANEL_NOT_FOUND",
    "technicians": "ERR_TECHNICIAN_NOT_FOUND",
    "recoveries": "ERR_RECOVERY_NOT_FOUND",
    "tissues": "ERR_TISSUE_NOT_FOUND",
    "surgeons": "ERR_SURGEON_NOT_FOUND",
    "requests": "ERR_REQUEST_NOT_FOUND",
    "allocations": "ERR_ALLOCATION_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
    "investigations": "ERR_INVESTIGATION_NOT_FOUND",
}


def lookup(collection, ident):
    """Resolve a path identifier; missing rows raise the collection's 404."""
    row = store.DB[collection].get(ident)
    if row is None:
        raise ApiError(NOT_FOUND[collection], "%s not found: %s" % (collection[:-1], ident))
    return row


def resolve_fk(body, field, collection):
    """Rung 5: resolve a body foreign key when it is present and shaped like an id."""
    if field not in body:
        return None
    value = body.get(field)
    if value is None or not isinstance(value, str):
        return None
    return lookup(collection, value)


# ------------------------------------------------------------------- scalars


def _fail(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def _present(body, field, required):
    if field not in body:
        if required:
            _fail(field, "is required.")
        return False
    return True


def req_str(body, field, min_len=None, max_len=None):
    _present(body, field, True)
    value = body.get(field)
    if not isinstance(value, str):
        _fail(field, "must be a string.")
    if min_len is not None and len(value) < min_len:
        _fail(field, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        _fail(field, "must be at most %d characters." % max_len)
    return value


def opt_str(body, field, min_len=None, max_len=None, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_str(body, field, min_len, max_len)


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        _fail(field, "must be one of %s." % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_int(body, field, minimum=None, maximum=None):
    _present(body, field, True)
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _fail(field, "must be at least %s." % minimum)
    if maximum is not None and value > maximum:
        _fail(field, "must be at most %s." % maximum)
    return value


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum, maximum)


def req_decimal(body, field, minimum=None, maximum=None):
    _present(body, field, True)
    value = body.get(field)
    if isinstance(value, bool):
        _fail(field, "must be a number.")
    if isinstance(value, (int, float)):
        parsed = Decimal(str(value))
    elif isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            _fail(field, "must be a number.")
    else:
        _fail(field, "must be a number.")
    if not parsed.is_finite():
        _fail(field, "must be a finite number.")
    if minimum is not None and parsed < Decimal(str(minimum)):
        _fail(field, "must be at least %s." % minimum)
    if maximum is not None and parsed > Decimal(str(maximum)):
        _fail(field, "must be at most %s." % maximum)
    return parsed


def req_dt(body, field):
    _present(body, field, True)
    return store.parse_iso(body.get(field))


def opt_dt(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return store.parse_iso(body.get(field))


def req_bool(body, field):
    _present(body, field, True)
    value = body.get(field)
    if not isinstance(value, bool):
        _fail(field, "must be a boolean.")
    return value


def req_str_list(body, field, allowed, min_len=1, max_len=2):
    _present(body, field, True)
    value = body.get(field)
    if not isinstance(value, list):
        _fail(field, "must be an array.")
    if len(value) < min_len or len(value) > max_len:
        _fail(field, "must contain between %d and %d entries." % (min_len, max_len))
    seen = set()
    for entry in value:
        if not isinstance(entry, str) or entry not in allowed:
            _fail(field, "entries must be one of %s." % ", ".join(sorted(allowed)))
        if entry in seen:
            _fail(field, "must not repeat a value.")
        seen.add(entry)
    return value


def filter_enum(name, value, allowed):
    """Query-string filters carry the same enum vocabulary as the stored field."""
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s filter is not a recognised value." % name)
    return value


def filter_bool(name, value):
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s filter must be true or false." % name)
