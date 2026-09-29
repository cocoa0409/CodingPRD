"""Shared foundation: in-memory store, logical clock, envelope, errors, auth, validation."""
import functools
import itertools
import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# Error catalogue (error_id -> HTTP status), transcribed from the spec.
# --------------------------------------------------------------------------
ERRORS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_BRANCH_NOT_FOUND": 404,
    "ERR_CURRENCY_NOT_FOUND": 404,
    "ERR_WHOLESALE_RATE_NOT_FOUND": 404,
    "ERR_CORRIDOR_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_RATE_CARD_NOT_FOUND": 404,
    "ERR_POSITION_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    # uniqueness
    "ERR_DUPLICATE_BRANCH_CODE": 409,
    "ERR_POSITION_ALREADY_EXISTS": 409,
    "ERR_CONTRACT_ALREADY_ISSUED": 409,
    # optimistic concurrency
    "ERR_STALE_BRANCH_VERSION": 412,
    "ERR_STALE_CUSTOMER_VERSION": 412,
    # state
    "ERR_RATE_CARD_NOT_DRAFT": 409,
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_TRANSACTION_NOT_QUOTED": 409,
    "ERR_TRANSACTION_NOT_AUTHORIZED": 409,
    "ERR_TRANSACTION_NOT_SETTLED": 409,
    "ERR_TRANSACTION_NOT_VOIDABLE": 409,
    "ERR_COMPLIANCE_DECISION_FINAL": 409,
    "ERR_CONTRACT_NOT_REDEEMABLE": 409,
    "ERR_CONTRACT_NOT_CANCELLABLE": 409,
    "ERR_ASSESSMENT_ALREADY_ASSESSED": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_SHIPMENT_INVALID_STATE": 409,
    # branch posture gates
    "ERR_BRANCH_NOT_ACTIVE": 409,
    "ERR_BRANCH_POSTURE_FROZEN": 409,
    "ERR_BRANCH_POSTURE_RESTRICTED": 409,
    # identification and compliance
    "ERR_CUSTOMER_ID_REQUIRED": 422,
    "ERR_CUSTOMER_ID_EXPIRED": 422,
    "ERR_CUSTOMER_COMPLIANCE_HOLD": 409,
    "ERR_TRANSACTION_COMPLIANCE_BLOCKED": 409,
    "ERR_STRUCTURING_REPORT_PENDING": 409,
    "ERR_RESTRICTED_CURRENCY_DOC_REQUIRED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DUAL_CONTROL_REQUIRED": 403,
    # temporal
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_REVERSAL_WINDOW_CLOSED": 409,
    "ERR_RATE_WINDOW_OVERLAP": 409,
    "ERR_ROUTE_WINDOW_CONFLICT": 409,
    "ERR_SHIPMENT_WINDOW_NOT_OPEN": 409,
    "ERR_PLAN_OUTSIDE_SEASON": 409,
    # business constraints
    "ERR_EXPORT_LIMIT_EXCEEDED": 422,
    "ERR_EXOTIC_PLAN_REQUIRED": 422,
    "ERR_DISCLOSURE_VERSION_UNSUPPORTED": 422,
    "ERR_PLAN_NO_TARGET_LINES": 422,
    "ERR_BUYBACK_NOT_ELIGIBLE": 422,
    "ERR_BUYBACK_BLOCKS_REVERSAL": 422,
    "ERR_REDEEM_EXCEEDS_REMAINING": 422,
    "ERR_OUTCOME_NOT_PERMITTED_FOR_DEFECT": 422,
    "ERR_ROUTE_SUSPENDED": 422,
    "ERR_ROUTE_BRANCH_NOT_SERVICED": 422,
    # rate-board referential
    "ERR_RATE_CARD_NOT_PUBLISHED": 409,
    "ERR_RATE_CARD_NOT_EFFECTIVE": 409,
    # fiscal capacity
    "ERR_DENOMINATION_NOT_STOCKED": 422,
    "ERR_INSUFFICIENT_INVENTORY": 422,
    "ERR_VAULT_LIMIT_WOULD_EXCEED": 422,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = ERRORS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "TreasuryOfficer",
    "BranchManager",
    "BranchTeller",
    "ComplianceOfficer",
    "Customer",
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COMMISSION_TIER_1_CEILING_CENTS = 25000
COMMISSION_TIER_2_CEILING_CENTS = 100000
COMMISSION_TIER_1_BPS = 350
COMMISSION_TIER_2_BPS = 250
COMMISSION_TIER_3_BPS = 150
COMMISSION_PREMIUM_UPLIFT_BPS = 50
COMMISSION_MIN_CENTS = 400

EXOTIC_PLAN_CAP_MINOR_UNITS = 5000000
RESTRICTED_EXPORT_MULTIPLE = 2
PLAN_VAULT_SHARE_BPS = 2500

VAULT_RESTRICTED_MIN_BPS = 9000
VAULT_FROZEN_MIN_BPS = 10000
VAULT_TARGET_BPS = 8500

NEAR_THRESHOLD_FLOOR_CENTS = 800000
REPORT_THRESHOLD_CENTS = 1000000
ROLLING_WINDOW_DAYS = 30

VOLUME_COMPONENT_MAX = 40
FREQUENCY_COMPONENT_MAX = 35
DISPERSION_COMPONENT_MAX = 25
NEAR_THRESHOLD_POINTS = 11
DISPERSION_POINTS = 12
RISK_TIER_ELEVATED_MIN = 25
RISK_TIER_HIGH_MIN = 70

BUYBACK_FEE_BPS = 300
BUYBACK_FEE_MIN_CENTS = 200
RATE_LOCK_DAYS = 31

MIN_ROUTE_GAP_MINUTES = 45
ID_REQUIRED_CENTS = 100000
DUAL_CONTROL_THRESHOLD_CENTS = 500000
QUOTE_TTL_MINUTES = 15
REVERSAL_WINDOW_HOURS = 24
MIN_DISCLOSURE_TEXT_VERSION = 3

# --------------------------------------------------------------------------
# In-memory store.  Starts EMPTY on every boot; nothing is ever seeded.
# --------------------------------------------------------------------------
KINDS = (
    "Branch",
    "CurrencyProfile",
    "WholesaleRate",
    "TravelCorridor",
    "ArmoredRoute",
    "RateCard",
    "InventoryPosition",
    "InventoryPlan",
    "Customer",
    "ExchangeTransaction",
    "BuybackContract",
    "NoteAssessment",
    "ComplianceReport",
    "CashShipment",
)

S = {k: {} for k in KINDS}
_seq_counter = itertools.count(1)
_clock = {"now": CLOCK_START}
LOCK = threading.RLock()

NOT_FOUND_FOR = {
    "Branch": "ERR_BRANCH_NOT_FOUND",
    "CurrencyProfile": "ERR_CURRENCY_NOT_FOUND",
    "WholesaleRate": "ERR_WHOLESALE_RATE_NOT_FOUND",
    "TravelCorridor": "ERR_CORRIDOR_NOT_FOUND",
    "ArmoredRoute": "ERR_ROUTE_NOT_FOUND",
    "RateCard": "ERR_RATE_CARD_NOT_FOUND",
    "InventoryPosition": "ERR_POSITION_NOT_FOUND",
    "InventoryPlan": "ERR_PLAN_NOT_FOUND",
    "Customer": "ERR_CUSTOMER_NOT_FOUND",
    "ExchangeTransaction": "ERR_TRANSACTION_NOT_FOUND",
    "BuybackContract": "ERR_CONTRACT_NOT_FOUND",
    "NoteAssessment": "ERR_ASSESSMENT_NOT_FOUND",
    "ComplianceReport": "ERR_REPORT_NOT_FOUND",
    "CashShipment": "ERR_SHIPMENT_NOT_FOUND",
}


def next_seq():
    return next(_seq_counter)


# --------------------------------------------------------------------------
# Logical clock and ISO-8601 helpers
# --------------------------------------------------------------------------
def clock():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        base = base - sign * offset
    return base


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_str():
    return fmt_dt(clock())


def D(value):
    """Row-field accessor: parse a stored ISO string into a datetime (or None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return parse_dt(value)


def month_start(dt):
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)


def utc_date(dt):
    return (dt.year, dt.month, dt.day)


# --------------------------------------------------------------------------
# Arithmetic: integers only, one rounding rule (round half up).
# --------------------------------------------------------------------------
def rhu(num, den):
    """round_half_up(num / den) on integers."""
    if den == 0:
        raise ApiError("ERR_INVALID_REQUEST", "Division by zero.")
    if den < 0:
        num, den = -num, -den
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def fdiv(num, den):
    """floor(num / den) on integers."""
    if den == 0:
        raise ApiError("ERR_INVALID_REQUEST", "Division by zero.")
    return num // den


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _touch_marker():
    try:
        marker = getattr(g, "_touched", None)
        if marker is None:
            marker = set()
            g._touched = marker
        return marker
    except RuntimeError:  # outside a request context
        return set()


def new_row(kind, audited=True):
    row = {"id": new_id()}
    row["_kind"] = kind
    row["_seq"] = next_seq()
    row["created_at"] = now_str()
    if audited:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    # Creation *is* version 1: a cascade later in this same request must not
    # bump a row that was born inside it.
    _touch_marker().add(row["id"])
    return row


def store(row):
    S[row["_kind"]][row["id"]] = row
    return row


def touch(row):
    """Bump version / updated_at at most once per request for this row."""
    if row is None or "version" not in row:
        return row
    marker = _touch_marker()
    if row["id"] in marker:
        return row
    marker.add(row["id"])
    row["version"] += 1
    row["updated_at"] = now_str()
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def all_rows(kind):
    return list(S[kind].values())


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def get_row(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return S[kind].get(row_id)


def need(kind, row_id):
    row = get_row(kind, row_id)
    if row is None:
        fail(NOT_FOUND_FOR[kind])
    return row


def currency(code):
    """Resolve a currency by its ISO 4217 natural key."""
    if not isinstance(code, str):
        return None
    for row in S["CurrencyProfile"].values():
        if row["iso_code"] == code:
            return row
    return None


def need_currency(code):
    row = currency(code)
    if row is None:
        fail("ERR_CURRENCY_NOT_FOUND")
    return row


# --------------------------------------------------------------------------
# Request envelope
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    rid = getattr(g, "_rid", None)
    if rid is None:
        rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
        g._rid = rid
    return rid


def wall_now():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": wall_now()}


def ok(data, code=200):
    return jsonify({"meta": base_meta(), "response_type": "object", "data": data}), code


def ok_list(items, page):
    meta = base_meta()
    meta["limit"] = page["limit"]
    meta["offset"] = page["offset"]
    meta["total_count"] = page["total_count"]
    meta["has_more"] = page["has_more"]
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, http):
    return (
        jsonify(
            {
                "meta": base_meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        http,
    )


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------
def endpoint(roles):
    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED")
            if role not in allowed:
                fail("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            with LOCK:
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


# --------------------------------------------------------------------------
# Body / query validation (rank 4: ERR_INVALID_REQUEST)
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


def _present(b, name):
    return name in b and b[name] is not None


def req_str(b, name, max_len=None, min_len=1):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = b[name]
    if not isinstance(value, str) or len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s is too long." % name)
    return value


def opt_str(b, name, default=None, max_len=None):
    if not _present(b, name):
        return default
    value = b[name]
    if not isinstance(value, str) or not value:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s is too long." % name)
    return value


def _as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    return value


def req_int(b, name, minimum=None, maximum=None):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = _as_int(b[name], name)
    _range(value, name, minimum, maximum)
    return value


def opt_int(b, name, default=None, minimum=None, maximum=None):
    if not _present(b, name):
        return default
    value = _as_int(b[name], name)
    _range(value, name, minimum, maximum)
    return value


def _range(value, name, minimum, maximum):
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d." % (name, maximum))


def req_enum(b, name, allowed):
    value = req_str(b, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(b, name, allowed, default=None):
    if not _present(b, name):
        return default
    value = b[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_bool(b, name, default=None):
    if not _present(b, name):
        return default
    value = b[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def req_dt(b, name):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    raw = b[name]
    if parse_dt(raw) is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 instant." % name)
    return raw


def opt_dt(b, name, default=None):
    if not _present(b, name):
        return default
    raw = b[name]
    if parse_dt(raw) is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 instant." % name)
    return raw


def req_list(b, name, allow_empty=False):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    value = b[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % name)
    if not value and not allow_empty:
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % name)
    return value


def opt_list(b, name, default=None):
    if not _present(b, name):
        return default
    value = b[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % name)
    return value


def parse_note_lines(raw, field, count_keys=("note_count",), min_count=1):
    """Parse a [{denomination_minor_units, note_count}] array. Denominations distinct."""
    out = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "%s entries must be objects." % field)
        denom = entry.get("denomination_minor_units")
        if isinstance(denom, bool) or not isinstance(denom, int) or denom < 1:
            fail("ERR_INVALID_REQUEST", "%s[].denomination_minor_units must be >= 1." % field)
        count = None
        for key in count_keys:
            if entry.get(key) is not None:
                count = entry[key]
                break
        if isinstance(count, bool) or not isinstance(count, int):
            fail("ERR_INVALID_REQUEST", "%s[].note_count must be an integer." % field)
        if count < min_count:
            fail("ERR_INVALID_REQUEST", "%s[].note_count must be >= %d." % (field, min_count))
        if denom in seen:
            fail("ERR_INVALID_REQUEST", "%s contains duplicate denominations." % field)
        seen.add(denom)
        out.append({"denomination_minor_units": denom, "note_count": count})
    out.sort(key=lambda e: e["denomination_minor_units"])
    return out


def require_standard_denominations(lines, profile, field):
    allowed = set(profile["standard_denominations"])
    for line in lines:
        if line["denomination_minor_units"] not in allowed:
            fail(
                "ERR_INVALID_REQUEST",
                "%s cites a denomination that is not in standard_denominations." % field,
            )


# --------------------------------------------------------------------------
# Pagination and filtering for list endpoints
# --------------------------------------------------------------------------
def paginate(rows):
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        if not re.match(r"^-?\d+$", raw or ""):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        if not re.match(r"^-?\d+$", raw or ""):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0.")
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qs_bool(name):
    value = qs(name)
    if value is None:
        return None
    low = value.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    return None


def filter_rows(rows, spec):
    """spec: {query_param: row_field}."""
    out = rows
    for param, field in spec.items():
        wanted = qs(param)
        if wanted is None:
            continue
        out = [r for r in out if str(r.get(field)) == wanted]
    return out


def filter_bool(rows, param, field):
    wanted = qs_bool(param)
    if wanted is None:
        return rows
    return [r for r in rows if bool(r.get(field)) is wanted]


def listing(kind, spec=None, bool_spec=None, order=None):
    rows = all_rows(kind)
    if spec:
        rows = filter_rows(rows, spec)
    if bool_spec:
        for param, field in bool_spec.items():
            rows = filter_bool(rows, param, field)
    rows = order(rows) if order else sort_created_asc(rows)
    page, meta = paginate(rows)
    return ok_list([public(r) for r in page], meta)


# --------------------------------------------------------------------------
# Shared gate helpers
# --------------------------------------------------------------------------
def require_branch_active(branch):
    if branch["status"] != "ACTIVE":
        fail("ERR_BRANCH_NOT_ACTIVE")


def require_not_frozen(branch):
    if branch["posture"] == "FROZEN":
        fail("ERR_BRANCH_POSTURE_FROZEN")


def require_not_restricted(branch):
    if branch["posture"] == "RESTRICTED":
        fail("ERR_BRANCH_POSTURE_RESTRICTED")
