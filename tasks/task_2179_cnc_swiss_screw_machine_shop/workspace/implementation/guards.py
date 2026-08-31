"""Auth ladder, body/query validation helpers, lookup helpers."""
from flask import request

from core import ROLES, db, fail, parse_dt, dec

MISSING = object()


# --------------------------------------------------------------------------
# priority 10 / 20 — authentication then authorization
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    return str(user_id), role


ALL_ROLES = list(ROLES)


# --------------------------------------------------------------------------
# priority 30 — request body well-formedness
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _present(payload, name, required):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return False
    return True


def f_str(payload, name, required=True, default=None, max_len=None, min_len=1):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % name)
    return value


def f_int(payload, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def f_num(payload, name, required=True, default=None, minimum=None, exclusive_min=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    number = dec(value)
    if minimum is not None and number < dec(minimum):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if exclusive_min is not None and number <= dec(exclusive_min):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (name, exclusive_min))
    return number


def f_bool(payload, name, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def f_enum(payload, name, allowed, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def f_dt(payload, name, required=True, default=None):
    """Returns (raw_string, aware_datetime) so the stored value echoes verbatim."""
    if not _present(payload, name, required):
        return default, None
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    return value, parsed


def f_enum_list(payload, name, allowed, required=False, default=None):
    if not _present(payload, name, required):
        return list(default) if default is not None else None
    value = payload[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains an illegal member." % name)
    return list(value)


def f_num_list(payload, name, required=True, default=None):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, list) or not value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array of numbers." % name)
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain only numbers." % name)
        out.append(dec(item))
    return out


# --------------------------------------------------------------------------
# pagination (priority 30)
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer >= 0.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


# --------------------------------------------------------------------------
# priority 40 / 45 — existence
# --------------------------------------------------------------------------
_NOT_FOUND = {
    "operators": "ERR_OPERATOR_NOT_FOUND",
    "machines": "ERR_MACHINE_NOT_FOUND",
    "parts": "ERR_PART_NOT_FOUND",
    "characteristics": "ERR_CHARACTERISTIC_NOT_FOUND",
    "gauges": "ERR_GAUGE_NOT_FOUND",
    "bar_stock_lots": "ERR_BAR_LOT_NOT_FOUND",
    "quotes": "ERR_QUOTE_NOT_FOUND",
    "blanket_pos": "ERR_BLANKET_PO_NOT_FOUND",
    "kanban_releases": "ERR_RELEASE_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "tool_assignments": "ERR_TOOL_ASSIGNMENT_NOT_FOUND",
    "spc_samples": "ERR_SPC_SAMPLE_NOT_FOUND",
    "routing_steps": "ERR_ROUTING_STEP_NOT_FOUND",
}


def lookup(collection, identifier):
    rows = getattr(db, collection)
    row = rows.get(identifier)
    if row is None:
        fail(_NOT_FOUND[collection])
    return row


def find(collection, identifier):
    return getattr(db, collection).get(identifier)


# --------------------------------------------------------------------------
# priority 50 — Machinist / Inspector identity must name an ACTIVE Operator
# --------------------------------------------------------------------------
def active_operator(user_id):
    operator = db.operators.get(user_id)
    if operator is None or operator.get("status") != "ACTIVE":
        fail("ERR_OPERATOR_NOT_FOUND")
    return operator


# --------------------------------------------------------------------------
# priority 98 — unique keys
# --------------------------------------------------------------------------
def ensure_unique(collection, field, value, scope_field=None, scope_value=None):
    for row in getattr(db, collection).values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        fail("ERR_DUPLICATE_KEY")


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
