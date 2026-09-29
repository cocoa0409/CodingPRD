"""Core infrastructure: in-memory store, response envelope, errors, auth, validation.

Landscape Supply Yard API. All structural names are taken from SCAFFOLD.yaml /
PRD.md: headers X-User-ID + X-User-Role, envelope meta/response_type/data,
error body data.error_id + data.message, pagination limit/offset/total_count/
has_more.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP

from flask import jsonify, request

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

ROLES = (
    "Contractor",
    "YardAdmin",
    "CreditManager",
    "DispatchPlanner",
    "YardLoader",
    "ClaimsAdjuster",
)

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# --------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACCOUNT_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_MATERIAL_NOT_FOUND": 404,
    "ERR_PRICE_SCHEDULE_NOT_FOUND": 404,
    "ERR_INVENTORY_LOT_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_PO_NOT_FOUND": 404,
    "ERR_PREBUY_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_TRUCK_NOT_FOUND": 404,
    "ERR_LOAD_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_CONTAINER_RETURN_NOT_FOUND": 404,
    "ERR_STALE_MATERIAL_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_ALREADY_TERMINAL": 409,
    "ERR_ORDER_NOT_FULFILLED": 409,
    "ERR_ORDER_HAS_DISPATCHED_LOAD": 409,
    "ERR_ORDER_NOT_ALLOCATABLE": 409,
    "ERR_LOAD_NOT_PLANNED": 409,
    "ERR_LOAD_NOT_DISPATCHED": 409,
    "ERR_LOAD_NOT_REFUSED": 409,
    "ERR_TICKET_NOT_STAGED": 409,
    "ERR_TICKET_NOT_LOADING": 409,
    "ERR_TICKET_NOT_LOADED": 409,
    "ERR_TICKET_NOT_CANCELLABLE": 409,
    "ERR_CLAIM_NOT_REVIEWABLE": 409,
    "ERR_CLAIM_NOT_APPROVED": 409,
    "ERR_PREBUY_NOT_DRAFT": 409,
    "ERR_CONTAINER_RETURN_CLOSED": 409,
    "ERR_PO_NOT_OPEN": 409,
    "ERR_MATERIAL_NOT_SELLABLE": 409,
    "ERR_LOT_QUARANTINED": 409,
    "ERR_TRUCK_UNAVAILABLE": 409,
    "ERR_ACCOUNT_CREDIT_HOLD": 409,
    "ERR_PREBUY_NOT_ACTIVE": 409,
    "ERR_SAFETY_ACK_REQUIRED": 422,
    "ERR_AXLE_WEIGHT_LIMIT_EXCEEDED": 422,
    "ERR_DRIVEWAY_ACCESS_RESTRICTED": 422,
    "ERR_DRIVEWAY_PROTECTION_REQUIRED": 422,
    "ERR_LOAD_EXCEEDS_TRUCK_CAPACITY": 422,
    "ERR_TRUCK_WINDOW_CONFLICT": 409,
    "ERR_PREBUY_SEASON_OVERLAP": 409,
    "ERR_STAGING_CAPACITY_FULL": 409,
    "ERR_WILL_CALL_QUEUE_EMPTY": 409,
    "ERR_ORDER_HAS_NO_LINES": 422,
    "ERR_DUPLICATE_SKU": 422,
    "ERR_DUPLICATE_PO_NUMBER": 422,
    "ERR_FORM_NOT_OFFERED": 422,
    "ERR_WILL_CALL_MODE_REQUIRED": 422,
    "ERR_DELIVERY_MODE_REQUIRED": 422,
    "ERR_PO_REQUIRED": 422,
    "ERR_PO_ACCOUNT_MISMATCH": 422,
    "ERR_CLAIM_TARGET_MISMATCH": 422,
    "ERR_MATERIAL_NOT_PREBUY_ELIGIBLE": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PRICE_SCHEDULE_BACKDATED": 422,
    "ERR_CLOCK_MUST_ADVANCE": 422,
    "ERR_PREBUY_OUT_OF_SEASON": 422,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_PREBUY_BALANCE_EXCEEDED": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_PO_LIMIT_EXCEEDED": 402,
    "ERR_DELIVERED_EXCEEDS_PLANNED": 422,
    "ERR_LOAD_EXCEEDS_ORDER_BALANCE": 422,
    "ERR_APPROVED_EXCEEDS_CLAIM": 422,
    "ERR_CLAIM_NOT_PAYABLE": 422,
    "ERR_RETURN_COUNT_EXCEEDS_ISSUED": 422,
    "ERR_UNDERPAYMENT": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Numeric helpers (PRD 2.6)
# --------------------------------------------------------------------------
CENT = Decimal("1")
TWO = Decimal("0.01")


def D(value):
    """Decimal from anything numeric without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def r2(value):
    """Volume convention: 2 decimal places, half up."""
    return float(D(value).quantize(TWO, rounding=ROUND_HALF_UP))


def d2(value):
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def floor2(value):
    """Payload headroom: truncated downward to 2 decimal places."""
    return float(D(value).quantize(TWO, rounding=ROUND_DOWN))


def cents(value):
    """Money / weight convention: whole integer, half up."""
    return int(D(value).quantize(CENT, rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).quantize(CENT, rounding=ROUND_UP))


def dsum(values):
    total = Decimal(0)
    for v in values:
        total += D(v)
    return total


# --------------------------------------------------------------------------
# Timestamp helpers (PRD 2.4: ISO 8601 UTC, exactly three fractional digits)
# --------------------------------------------------------------------------
_last_ms = [0]


def _now_dt():
    ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if ms <= _last_ms[0]:
        ms = _last_ms[0] + 1
    _last_ms[0] = ms
    return EPOCH + timedelta(milliseconds=ms)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(_now_dt())


def parse_instant(raw):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(raw):
    """Parse a plain YYYY-MM-DD calendar date; returns the normalised string."""
    if not isinstance(raw, str) or len(raw.strip()) != 10:
        return None
    try:
        d = datetime.strptime(raw.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return d.strftime("%Y-%m-%d")


def epoch_seconds(dt):
    return (dt - EPOCH).total_seconds()


# --------------------------------------------------------------------------
# In-memory store.  Starts completely empty on every boot: nothing is seeded.
# --------------------------------------------------------------------------
COLLECTIONS = (
    "materials",
    "price_schedules",
    "inventory_lots",
    "contractor_accounts",
    "job_purchase_orders",
    "prebuy_contracts",
    "material_orders",
    "order_lines",
    "delivery_trucks",
    "delivery_loads",
    "will_call_tickets",
    "claim_cases",
    "container_returns",
)

NOT_FOUND = {
    "materials": "ERR_MATERIAL_NOT_FOUND",
    "price_schedules": "ERR_PRICE_SCHEDULE_NOT_FOUND",
    "inventory_lots": "ERR_INVENTORY_LOT_NOT_FOUND",
    "contractor_accounts": "ERR_ACCOUNT_NOT_FOUND",
    "job_purchase_orders": "ERR_PO_NOT_FOUND",
    "prebuy_contracts": "ERR_PREBUY_NOT_FOUND",
    "material_orders": "ERR_ORDER_NOT_FOUND",
    "order_lines": "ERR_ORDER_LINE_NOT_FOUND",
    "delivery_trucks": "ERR_TRUCK_NOT_FOUND",
    "delivery_loads": "ERR_LOAD_NOT_FOUND",
    "will_call_tickets": "ERR_TICKET_NOT_FOUND",
    "claim_cases": "ERR_CLAIM_NOT_FOUND",
    "container_returns": "ERR_CONTAINER_RETURN_NOT_FOUND",
}


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_instant(DEFAULT_CLOCK_ISO)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def rows(self, name):
        """All rows of a collection in created_at ascending order."""
        return sorted(getattr(self, name).values(), key=lambda r: r["_seq"])

    def get(self, name, key):
        if not isinstance(key, str):
            return None
        return getattr(self, name).get(key)

    def insert(self, name, record):
        getattr(self, name)[record["id"]] = record
        return record


db = Store()


def new_record(**fields):
    stamp = now_iso()
    record = {"id": str(uuid.uuid4())}
    record.update(fields)
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1
    return record


def by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }


def respond(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# Authentication / authorisation (PRD 2.1, ladder rungs 1-3)
# --------------------------------------------------------------------------
class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_contractor(self):
        return self.role == "Contractor"


def auth(*allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return Ctx(user_id.strip(), role)


def scope(ctx, account_id):
    """Rung 3: a Contractor may only reach its own account's resources."""
    if ctx.is_contractor and account_id is not None and account_id != ctx.user_id:
        fail("ERR_ACCOUNT_SCOPE_VIOLATION", "Resource belongs to another account.")


def order_account_id(order):
    return None if order is None else order.get("contractor_account_id")


def scope_via_order(ctx, order):
    scope(ctx, order_account_id(order))


def scope_via_order_id(ctx, order_id):
    scope_via_order(ctx, db.get("material_orders", order_id))


# --------------------------------------------------------------------------
# Request-shape validation (rung 5) -- every failure is ERR_INVALID_REQUEST
# --------------------------------------------------------------------------
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, min_len=1, max_len=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must have at least %d character(s)" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must have at most %d characters" % max_len)
    return value


def opt_str(data, field, default=None, min_len=1, max_len=None):
    if not present(data, field):
        return default
    return req_str(data, field, min_len=min_len, max_len=max_len)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def _as_number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    return value


def req_num(data, field, minimum=None, maximum=None, exclusive_min=False):
    if not present(data, field):
        _bad(field, "is required")
    value = _as_number(field, data[field])
    dec = D(value)
    if exclusive_min and minimum is not None and dec <= D(minimum):
        _bad(field, "must be strictly greater than %s" % minimum)
    if not exclusive_min and minimum is not None and dec < D(minimum):
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and dec > D(maximum):
        _bad(field, "must be at most %s" % maximum)
    return float(value)


def opt_num(data, field, default=None, minimum=None, maximum=None, exclusive_min=False):
    if not present(data, field):
        return default
    return req_num(data, field, minimum=minimum, maximum=maximum,
                   exclusive_min=exclusive_min)


def req_int(data, field, minimum=None, maximum=None, exclusive_min=False):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            _bad(field, "must be an integer")
    if exclusive_min and minimum is not None and value <= minimum:
        _bad(field, "must be strictly greater than %s" % minimum)
    if not exclusive_min and minimum is not None and value < minimum:
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %s" % maximum)
    return int(value)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_bool(data, field):
    if not present(data, field):
        _bad(field, "is required")
    if not isinstance(data[field], bool):
        _bad(field, "must be a boolean")
    return data[field]


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    return req_bool(data, field)


def req_instant(data, field):
    if not present(data, field):
        _bad(field, "is required")
    parsed = parse_instant(data[field])
    if parsed is None:
        _bad(field, "must be an ISO 8601 instant")
    return parsed


def req_id(data, field):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str) or not value:
        _bad(field, "must be a string identifier")
    return value


def opt_id(data, field):
    if not present(data, field):
        return None
    return req_id(data, field)


def req_season_date(data, field):
    if not present(data, field):
        _bad(field, "is required")
    parsed = parse_date(data[field])
    if parsed is None:
        _bad(field, "must be a calendar date in YYYY-MM-DD form")
    return parsed


# --------------------------------------------------------------------------
# Pagination (PRD 2.3) -- validated at rung 5
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if str(raw_limit).strip() != str(limit):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if str(raw_offset).strip() != str(offset):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be at least 0")
    return limit, offset


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def arg_bool(name):
    value = arg(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad(name, "must be a boolean")


def render_list(rows, serializer):
    limit, offset = pagination()
    ordered = by_created(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Existence resolution (rungs 6 and 7)
# --------------------------------------------------------------------------
def require(record, collection):
    if record is None:
        fail(NOT_FOUND[collection])
    return record


def fk(data, field, collection):
    """Required body foreign key -> resolved record (rung 7)."""
    key = req_id(data, field)
    return require(db.get(collection, key), collection)


def opt_fk(data, field, collection):
    key = opt_id(data, field)
    if key is None:
        return None
    return require(db.get(collection, key), collection)


def pre_scope_account(ctx, data, field="contractor_account_id"):
    """Rung 3 runs before rung 5, so scope is judged on the raw body value."""
    if not ctx.is_contractor:
        return
    value = data.get(field)
    if isinstance(value, str) and value and value != ctx.user_id:
        fail("ERR_ACCOUNT_SCOPE_VIOLATION", "Resource belongs to another account.")


def pre_scope_order(ctx, data, field="material_order_id"):
    if not ctx.is_contractor:
        return
    value = data.get(field)
    if isinstance(value, str) and value:
        order = db.get("material_orders", value)
        if order is not None and order["contractor_account_id"] != ctx.user_id:
            fail("ERR_ACCOUNT_SCOPE_VIOLATION", "Order belongs to another account.")


def contractor_filter(ctx, rows, account_of):
    """List endpoints: a Contractor only ever sees its own account's rows."""
    if not ctx.is_contractor:
        return rows
    return [r for r in rows if account_of(r) == ctx.user_id]
