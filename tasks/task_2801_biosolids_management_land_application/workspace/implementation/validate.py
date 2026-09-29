"""Request parsing and schema validation (PRD priority 5)."""

import json
from decimal import Decimal

from flask import request

from errors import fail
from store import D, parse_dt

MISSING = object()


def get_body():
    """Parse the JSON body, keeping decimals exact. Absent body means {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def is_number(value):
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def present(body, key):
    return key in body and body[key] is not None


def vstr(body, key, required=True, min_len=1, max_len=None, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if min_len is not None and len(value.strip()) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-blank." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' exceeds %d characters." % (key, max_len))
    return value


def vnum(body, key, required=True, default=None, gt=None, ge=None, lt=None, le=None,
         nullable=False):
    if key not in body or body[key] is None:
        if key in body and body[key] is None and nullable:
            return None
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not is_number(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    value = D(value)
    if gt is not None and not value > D(gt):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (key, gt))
    if ge is not None and not value >= D(ge):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (key, ge))
    if lt is not None and not value < D(lt):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be less than %s." % (key, lt))
    if le is not None and not value <= D(le):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (key, le))
    return value


def vint(body, key, required=True, default=None, ge=None, le=None, gt=None, lt=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, Decimal) and value == value.to_integral_value():
            value = int(value)
        else:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if ge is not None and value < ge:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (key, ge))
    if le is not None and value > le:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (key, le))
    if gt is not None and not value > gt:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (key, gt))
    if lt is not None and not value < lt:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be less than %s." % (key, lt))
    return value


def vbool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def venum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def vdt(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % key)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed


def vid(body, key, required=True):
    """Foreign key shape check only; existence is priority 4."""
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return None
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string identifier." % key)
    return value


def vmonths(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % key)
    months = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            if isinstance(item, Decimal) and item == item.to_integral_value():
                item = int(item)
            else:
                fail("ERR_INVALID_REQUEST", "Field '%s' must contain integers." % key)
        if item < 1 or item > 12:
            fail("ERR_INVALID_REQUEST", "Field '%s' entries must be within 1 through 12." % key)
        months.append(item)
    for i in range(1, len(months)):
        if months[i] <= months[i - 1]:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be strictly ascending." % key)
    return months


# --- query parameters ------------------------------------------------------


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except Exception:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be within 1 through 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except Exception:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def qenum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not a recognised member." % name)
    return value


def qstr(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qint(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except Exception:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def qbool(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# --- body foreign keys (PRD priority 4) ------------------------------------

FK_ORDER = [
    ("facility_id", "facilities", "ERR_FACILITY_NOT_FOUND"),
    ("site_id", "sites", "ERR_SITE_NOT_FOUND"),
    ("batch_id", "batches", "ERR_BATCH_NOT_FOUND"),
    ("agreement_id", "agreements", "ERR_AGREEMENT_NOT_FOUND"),
    ("outlet_id", "outlets", "ERR_OUTLET_NOT_FOUND"),
    ("event_id", "events", "ERR_EVENT_NOT_FOUND"),
]


def resolve_fks(body, keys):
    """Resolve body foreign keys in the canonical field order.

    Only well-formed non-blank string values are resolved here; a missing or
    wrongly typed value is left to the schema layer at priority 5.
    """
    import store as _store

    resolved = {}
    for key, collection_name, error_id in FK_ORDER:
        if key not in keys:
            continue
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            collection = getattr(_store, collection_name)
            record = collection.get(value)
            if record is None:
                fail(error_id, "%s %s does not exist." % (key, value))
            resolved[key] = record
    return resolved
