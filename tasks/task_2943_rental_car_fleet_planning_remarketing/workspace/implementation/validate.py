"""Request-schema validation helpers (validation rank 7) and lookup helpers.

Unknown body fields, and attempts to write system-managed or computed fields,
are silently ignored: nothing in this module rejects an extra key.
"""

from flask import request

from errors import ApiError
from store import parse_instant, store


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def _bad(field, detail):
    return ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def missing(payload, field):
    return field not in payload or payload[field] is None


def s_str(payload, field, required=True, allow_empty=False, exact_len=None, pattern=None):
    if missing(payload, field):
        if required:
            raise _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, str):
        raise _bad(field, "must be a string")
    if not allow_empty and value.strip() == "":
        raise _bad(field, "must be a non-empty string")
    if exact_len is not None and len(value) != exact_len:
        raise _bad(field, "must be exactly %d characters" % exact_len)
    if pattern is not None and not pattern.match(value):
        raise _bad(field, "does not match the required format")
    return value


def s_int(payload, field, required=True, ge=None, gt=None, error_id=None):
    if missing(payload, field):
        if required:
            if error_id:
                raise ApiError(error_id, "Field '%s' is required." % field)
            raise _bad(field, "is required")
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        if error_id:
            raise ApiError(error_id, "Field '%s' must be an integer." % field)
        raise _bad(field, "must be an integer")
    if ge is not None and value < ge:
        if error_id:
            raise ApiError(error_id, "Field '%s' must be at least %s." % (field, ge))
        raise _bad(field, "must be at least %s" % ge)
    if gt is not None and value <= gt:
        if error_id:
            raise ApiError(error_id, "Field '%s' must be greater than %s." % (field, gt))
        raise _bad(field, "must be greater than %s" % gt)
    return value


def s_num(payload, field, required=True, ge=None, gt=None, le=None, lt=None):
    if missing(payload, field):
        if required:
            raise _bad(field, "is required")
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(field, "must be a number")
    if ge is not None and value < ge:
        raise _bad(field, "must be at least %s" % ge)
    if gt is not None and value <= gt:
        raise _bad(field, "must be greater than %s" % gt)
    if le is not None and value > le:
        raise _bad(field, "must be at most %s" % le)
    if lt is not None and value >= lt:
        raise _bad(field, "must be less than %s" % lt)
    return value


def s_bool(payload, field, required=True):
    if missing(payload, field):
        if required:
            raise _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, bool):
        raise _bad(field, "must be a boolean")
    return value


def s_enum(payload, field, allowed, required=True):
    if missing(payload, field):
        if required:
            raise _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        raise _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def s_instant(payload, field, required=True):
    """Returns (raw_string, datetime) or (None, None)."""
    if missing(payload, field):
        if required:
            raise _bad(field, "is required")
        return None, None
    raw = payload[field]
    parsed = parse_instant(raw)
    if parsed is None:
        raise _bad(field, "must be an ISO-8601 UTC instant")
    return raw, parsed


def s_id(payload, field, required=True):
    """A foreign-key string; existence is checked separately at rank 6."""
    if missing(payload, field):
        if required:
            raise _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        raise _bad(field, "must be a non-empty string")
    return value


# -- existence lookups (validation ranks 5 and 6) ----------------------

_COLLECTIONS = {
    "market": ("markets", "ERR_MARKET_NOT_FOUND"),
    "segment": ("segments", "ERR_SEGMENT_NOT_FOUND"),
    "program": ("programs", "ERR_PROGRAM_NOT_FOUND"),
    "channel": ("channels", "ERR_CHANNEL_NOT_FOUND"),
    "policy": ("policies", "ERR_POLICY_NOT_FOUND"),
    "plan": ("plans", "ERR_FLEET_PLAN_NOT_FOUND"),
    "allocation": ("allocations", "ERR_ALLOCATION_NOT_FOUND"),
    "vehicle": ("vehicles", "ERR_VEHICLE_NOT_FOUND"),
    "task": ("tasks", "ERR_TASK_NOT_FOUND"),
    "order": ("orders", "ERR_ORDER_NOT_FOUND"),
    "damage_event": ("damage_events", "ERR_DAMAGE_EVENT_NOT_FOUND"),
    "consignment": ("consignments", "ERR_CONSIGNMENT_NOT_FOUND"),
    "ledger_entry": ("ledger", "ERR_LEDGER_ENTRY_NOT_FOUND"),
}


def load(kind, row_id):
    collection_name, error_id = _COLLECTIONS[kind]
    collection = getattr(store, collection_name)
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, "No %s exists with id '%s'." % (kind.replace("_", " "), row_id))
    return row


def find_fk(kind, row_id):
    """Body foreign key: skip when absent (schema rank catches it), else 404."""
    if row_id is None:
        return None
    return load(kind, row_id)


def body_fk(payload, field, kind):
    """Rank-6 resolution of one body foreign key.

    A value that is absent, null or not a string is left to the schema rank so
    that the reported error is ERR_INVALID_REQUEST rather than a 404.
    """
    raw = payload.get(field)
    if not isinstance(raw, str) or raw.strip() == "":
        return None
    return load(kind, raw)
