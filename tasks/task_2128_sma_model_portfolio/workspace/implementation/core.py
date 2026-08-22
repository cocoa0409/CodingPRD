"""Core infrastructure: errors, envelope, store, clock, auth, validation.

Every structural name in this module is taken verbatim from SCAFFOLD.yaml
(response_envelope, validations[], errors[], roles[]) and PRD.md sections 2.1-2.11.
"""

import random
import re
import string
import uuid
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1 / scaffold 1.7)
# ---------------------------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PORTFOLIO_MANAGER = "PortfolioManager"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_SPONSOR_OPERATOR = "SponsorOperator"
ROLE_BILLING_OFFICER = "BillingOfficer"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PORTFOLIO_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_SPONSOR_OPERATOR,
    ROLE_BILLING_OFFICER,
)
READ_ROLES = ALL_ROLES

# ---------------------------------------------------------------------------
# Error catalog (scaffold 1.6 / PRD 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SPONSOR_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SECURITY_NOT_FOUND": 404,
    "ERR_SPONSOR_NOT_FOUND": 404,
    "ERR_MODEL_NOT_FOUND": 404,
    "ERR_MODEL_VERSION_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_RESTRICTION_NOT_FOUND": 404,
    "ERR_TRADE_ORDER_NOT_FOUND": 404,
    "ERR_BLOCK_NOT_FOUND": 404,
    "ERR_TAX_LOT_NOT_FOUND": 404,
    "ERR_HARVEST_PROPOSAL_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_SUSPENDED": 409,
    "ERR_ACCOUNT_WRITTEN_OFF": 409,
    "ERR_ACCOUNT_NOT_DRIFTED": 409,
    "ERR_MODEL_NOT_PUBLISHED": 409,
    "ERR_MODEL_VERSION_NOT_PUBLISHED": 409,
    "ERR_DISTRIBUTION_NOT_ACTIVE": 409,
    "ERR_DISTRIBUTION_WINDOW_OVERLAP": 409,
    "ERR_BILLING_PERIOD_OVERLAP": 409,
    "ERR_PAYMENT_TERM_NOT_ELAPSED": 409,
    "ERR_UNWIND_BLOCKED": 409,
    "ERR_WEIGHTS_NOT_BALANCED": 422,
    "ERR_SECURITY_RESTRICTED": 422,
    "ERR_WASH_SALE_WINDOW_CONFLICT": 422,
    "ERR_HARVEST_BUDGET_EXCEEDED": 422,
    "ERR_INSUFFICIENT_SHARES": 422,
    "ERR_INSUFFICIENT_CASH": 422,
    "ERR_BELOW_SPONSOR_MINIMUM": 422,
    "ERR_BLOCK_COMPOSITION_INVALID": 422,
    "ERR_FILL_EXCEEDS_REQUEST": 422,
    "ERR_NO_TRADES_GENERATED": 422,
    "ERR_DISPERSION_SET_EMPTY": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

_last_dt = [datetime(1970, 1, 1, tzinfo=timezone.utc)]
_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def wall_now():
    """Monotonic non-decreasing wall clock, truncated to milliseconds.

    Used only for the housekeeping `created_at` / `updated_at` audit fields and
    the response envelope timestamp.  Every *business* instant comes from the
    logical clock (PRD 2.5).
    """
    dt = datetime.now(timezone.utc)
    dt = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
    if dt < _last_dt[0]:
        dt = _last_dt[0]
    _last_dt[0] = dt
    return dt


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute),
                      int(second or 0), micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offs = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offs
    return dt


def day_floor(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def whole_days(start, end):
    """Whole days elapsed from `start` to `end` (floor)."""
    return (end - start).days


# ---------------------------------------------------------------------------
# In-memory store.  Starts EMPTY on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    COLLECTIONS = (
        "securities", "sponsors", "models", "model_versions",
        "sponsor_distributions", "accounts", "account_restrictions",
        "trade_orders", "blocks", "tax_lots", "harvest_proposals",
        "fee_invoices",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK


db = Store()


def clock():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_row(**fields):
    ts = wall_now()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Bump version + updated_at once per row per request (PRD 2.4)."""
    if row is None:
        return row
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = id(row)
    if key in touched:
        return row
    touched.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = wall_now()
    return row


# ---------------------------------------------------------------------------
# Response envelope (scaffold 1.0 / PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
    return {"api_request_id": rid, "api_request_timestamp": fmt_dt(wall_now())}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(row, extra=None):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Auth (ladder rungs 1-4)
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role names an unknown role.")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE",
                               "Role %s may not perform this operation." % g.role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def sponsor_scope(sponsor_id):
    """Ladder rung 3 - only applies while acting as SponsorOperator."""
    if g.role == ROLE_SPONSOR_OPERATOR and g.user_id != sponsor_id:
        raise ApiError("ERR_SPONSOR_SCOPE_VIOLATION",
                       "SponsorOperator may only act within its own sponsor.")


# ---------------------------------------------------------------------------
# Lookup (ladder rungs 5-6)
# ---------------------------------------------------------------------------
def lookup(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# ---------------------------------------------------------------------------
# Request body validation (ladder rung 7)
# ---------------------------------------------------------------------------
_MISSING = object()


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def v_int(body, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be <= %d." % (name, maximum))
    return value


def v_str(body, name, required=True, min_len=1, max_len=None, pattern=None, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is too long." % name)
    if pattern is not None and not re.fullmatch(pattern, value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' has an invalid format." % name)
    return value


def v_bool(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def v_enum(body, name, members, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in members:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def v_dt(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    parsed = parse_dt(body[name])
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 instant." % name)
    return parsed


# ---------------------------------------------------------------------------
# Pagination (scaffold 1.0 / PRD 2.3)
# ---------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.fullmatch(r"[+-]?\d+", raw.strip()):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(raw)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _query_int("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def default_sort_key(row):
    return (row["created_at"], row["_seq"])


def sequence_sort_key(row):
    return (row["created_at"], row.get("sequence_number", 0))


def paged(rows, sort_key=default_sort_key, serializer=serialize):
    limit, offset = pagination()
    rows = sorted(rows, key=sort_key)
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def qfilter(rows, **filters):
    out = []
    for row in rows:
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# ---------------------------------------------------------------------------
# Exact rational rounding helpers (PRD 2.8)
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """Round numerator/denominator half away from zero, returning an int."""
    if denominator == 0:
        raise ZeroDivisionError("round_half_up by zero")
    negative = (numerator < 0) != (denominator < 0)
    n = abs(numerator)
    d = abs(denominator)
    q, r = divmod(n, d)
    if 2 * r >= d:
        q += 1
    return -q if negative else q
