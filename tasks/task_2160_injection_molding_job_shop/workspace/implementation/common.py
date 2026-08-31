"""Shared foundation: logical clock, error catalogue, response envelope, store."""
import random
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import request, jsonify, g

# ---------------------------------------------------------------- roles ----
ROLES = (
    "PlantAdmin",
    "SalesEngineer",
    "ProcessEngineer",
    "QualityEngineer",
    "ToolroomTech",
    "CustomerRep",
)

# ------------------------------------------------------- error catalogue ----
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_WINDOW": 400,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PRESS_NOT_FOUND": 404,
    "ERR_MOLD_NOT_FOUND": 404,
    "ERR_QUALIFICATION_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_PPAP_SUBMISSION_NOT_FOUND": 404,
    "ERR_RESIN_LOT_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_MAINTENANCE_ORDER_NOT_FOUND": 404,
    "ERR_TOOL_TRANSFER_NOT_FOUND": 404,
    "ERR_CAPACITY_COMMIT_NOT_FOUND": 404,
    "ERR_STALE_PRESS_VERSION": 412,
    "ERR_STALE_JOB_VERSION": 412,
    "ERR_STALE_MOLD_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_QUOTE_NOT_PRICED": 409,
    "ERR_JOB_NOT_SCHEDULED": 409,
    "ERR_JOB_NOT_RUNNING": 409,
    "ERR_JOB_NOT_BLOCKED": 409,
    "ERR_JOB_MATERIAL_NOT_STAGED": 409,
    "ERR_REPORT_ALREADY_REVERSED": 409,
    "ERR_TRANSFER_NOT_APPROVED": 409,
    "ERR_CAPACITY_COMMIT_NOT_OPEN": 409,
    "ERR_RUN_AT_RATE_NOT_SCHEDULED": 409,
    "ERR_MOLD_NOT_PPAP_APPROVED": 409,
    "ERR_MOLD_QUARANTINED": 409,
    "ERR_MOLD_TRANSFERRED": 409,
    "ERR_MOLD_RETIRED": 409,
    "ERR_PM_OVERDUE": 409,
    "ERR_MOLD_TRANSFER_IN_PROGRESS": 409,
    "ERR_FAI_NOT_PASSED": 422,
    "ERR_RESIN_LOT_NOT_RELEASED": 422,
    "ERR_RESIN_GRADE_MISMATCH": 422,
    "ERR_RESIN_MOISTURE_TOO_HIGH": 422,
    "ERR_PRESS_OFFLINE": 409,
    "ERR_PRESS_TONNAGE_MISMATCH": 422,
    "ERR_PRESS_SHOT_SIZE_EXCEEDED": 422,
    "ERR_PRESS_NOT_QUALIFIED": 422,
    "ERR_NO_ELIGIBLE_PRESS": 422,
    "ERR_PRESS_WINDOW_CONFLICT": 409,
    "ERR_MOLD_WINDOW_CONFLICT": 409,
    "ERR_PARTS_BALANCE_MISMATCH": 422,
    "ERR_REGRIND_RATIO_EXCEEDED": 422,
    "ERR_RESIN_LOT_INSUFFICIENT": 422,
    "ERR_PRESS_DAILY_CAPACITY_EXCEEDED": 422,
    "ERR_CAPACITY_COMMIT_EXCEEDED": 422,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_QUALIFICATION": 409,
    "ERR_MAINTENANCE_ALREADY_OPEN": 409,
    "ERR_CUSTOMER_CREDIT_HOLD": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ------------------------------------------------------- logical clock ----
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.current = INITIAL_CLOCK


CLOCK = _Clock()
LOCK = threading.RLock()


def now_dt():
    return CLOCK.current


def set_clock(dt):
    CLOCK.current = dt


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns a tz-aware datetime or None."""
    if not isinstance(value, str):
        return None
    txt = value.strip()
    if not txt:
        return None
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    if dt.utcoffset() != timedelta(0):
        return None
    return dt.astimezone(timezone.utc)


def is_whole_minute(dt):
    return dt.second == 0 and dt.microsecond == 0


# --------------------------------------------------------------- store ----
class Store:
    COLLECTIONS = (
        "customers", "presses", "molds", "qualifications", "quotes", "ppaps",
        "resin_lots", "jobs", "reports", "maintenance_orders", "transfers", "commits",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_entity(fields):
    stamp = iso(now_dt())
    entity = {"id": str(uuid.uuid4())}
    entity.update(fields)
    entity["created_at"] = stamp
    entity["updated_at"] = stamp
    entity["version"] = 1
    entity["_created_dt"] = now_dt()
    entity["_seq"] = DB.next_seq()
    return entity


def order_key(entity):
    """Sort/compare key: created_at ascending, creation sequence as the stable
    tie-break. No ordering rule anywhere in this system reads `id`."""
    return (entity["_created_dt"], entity["_seq"])


def touch(entity):
    entity["updated_at"] = iso(now_dt())
    entity["version"] += 1


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sorted_values(collection):
    return sorted(collection.values(), key=order_key)


# ------------------------------------------------------------ envelope ----
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": iso(now_dt())}


def respond(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def respond_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), code


# ---------------------------------------------------------------- auth ----
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unrecognised authentication headers.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    g.user_id = user_id
    g.role = role


def endpoint(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                authenticate(allowed_roles)
                return fn(*args, **kwargs)
        return wrapper
    return decorator


# ------------------------------------------------- lookup / pagination ----
_NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "presses": "ERR_PRESS_NOT_FOUND",
    "molds": "ERR_MOLD_NOT_FOUND",
    "qualifications": "ERR_QUALIFICATION_NOT_FOUND",
    "quotes": "ERR_QUOTE_NOT_FOUND",
    "ppaps": "ERR_PPAP_SUBMISSION_NOT_FOUND",
    "resin_lots": "ERR_RESIN_LOT_NOT_FOUND",
    "jobs": "ERR_JOB_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
    "maintenance_orders": "ERR_MAINTENANCE_ORDER_NOT_FOUND",
    "transfers": "ERR_TOOL_TRANSFER_NOT_FOUND",
    "commits": "ERR_CAPACITY_COMMIT_NOT_FOUND",
}


def lookup(collection_name, resource_id):
    collection = getattr(DB, collection_name)
    if not isinstance(resource_id, str) or resource_id not in collection:
        fail(_NOT_FOUND[collection_name])
    return collection[resource_id]


def page_params():
    args = request.args
    limit = 10
    offset = 0
    if args.get("limit") is not None:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if args.get("offset") is not None:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def filter_value(name, allowed=None):
    """Read an optional query filter, validating enum membership when declared."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if allowed is not None and raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Unknown value for filter %s." % name)
    return raw


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Filter %s must be a boolean." % name)


def filter_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Filter %s must be an integer." % name)


def list_response(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return respond_list([public(r) for r in window], limit, offset, total)
