"""Core infrastructure: logical clock, in-memory store, response envelope,
error catalogue, authentication / RBAC and request validation helpers.

Every structural name in this module is taken from PRD.md §2 and
SCAFFOLD.yaml §1.0 / §1.4 / §1.7 -- nothing is assumed.
"""

import functools
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Error catalogue (PRD §5 / SCAFFOLD §1.6)
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_LEAD_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_ANALYSIS_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_BLOCK_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_RECONCILIATION_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_STALE_LEAD_VERSION": 412,
    "ERR_STALE_BLOCK_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_LEAD_INVALID_STATE": 409,
    "ERR_QUOTE_INVALID_STATE": 409,
    "ERR_CONTRACT_INVALID_STATE": 409,
    "ERR_BLOCK_INVALID_STATE": 409,
    "ERR_BLOCK_NOT_OPEN": 409,
    "ERR_RESERVATION_INVALID_STATE": 409,
    "ERR_CHARGE_INVALID_STATE": 409,
    "ERR_HOLD_INVALID_STATE": 409,
    "ERR_ANALYSIS_ALREADY_DECIDED": 409,
    "ERR_RECONCILIATION_ALREADY_FINALIZED": 409,
    "ERR_BLOCK_ALREADY_BILLED": 409,
    "ERR_RECEIVABLE_ALREADY_SETTLED": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_QUOTE_EXPIRED": 422,
    "ERR_PAST_CUTOFF_DATE": 422,
    "ERR_CUTOFF_DATE_NOT_REACHED": 422,
    "ERR_CANCEL_AFTER_ARRIVAL": 422,
    "ERR_EVENT_NOT_CONCLUDED": 422,
    "ERR_DISPLACEMENT_NOT_APPROVED": 409,
    "ERR_INVENTORY_DAY_MISSING": 422,
    "ERR_SUB_BLOCK_DATES_OUTSIDE_PARENT": 422,
    "ERR_STAY_DATE_OUTSIDE_BLOCK": 422,
    "ERR_BLOCKS_NOT_CUT_OFF": 409,
    "ERR_ALLOTMENT_PLAN_MISMATCH": 422,
    "ERR_DUPLICATE_ROOMING_LIST_ENTRY": 409,
    "ERR_FUNCTION_SPACE_CONFLICT": 409,
    "ERR_CONCESSION_INELIGIBLE": 422,
    "ERR_DISCOUNT_STACK_EXCEEDED": 422,
    "ERR_GROUP_CEILING_EXCEEDED": 409,
    "ERR_BLOCK_ALLOTMENT_EXCEEDED": 409,
    "ERR_SUB_BLOCK_ALLOTMENT_EXCEEDED": 409,
    "ERR_DISPLACEMENT_NET_BENEFIT_NEGATIVE": 422,
    "ERR_ACCOUNT_CREDIT_HOLD": 402,
    "ERR_NOT_FOUND": 404,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Roles (PRD §2.1 / SCAFFOLD §1.7)
# ---------------------------------------------------------------------------

ROLE_SALES_MANAGER = "SalesManager"
ROLE_REVENUE_MANAGER = "RevenueManager"
ROLE_CONTRACT_ADMIN = "ContractAdmin"
ROLE_RESERVATIONS_AGENT = "ReservationsAgent"
ROLE_ACCOUNTING_CLERK = "AccountingClerk"
ROLE_GROUP_CONTACT = "GroupContact"
ROLE_SYSTEM_OPERATOR = "SystemOperator"

ALL_ROLES = {
    ROLE_SALES_MANAGER,
    ROLE_REVENUE_MANAGER,
    ROLE_CONTRACT_ADMIN,
    ROLE_RESERVATIONS_AGENT,
    ROLE_ACCOUNTING_CLERK,
    ROLE_GROUP_CONTACT,
    ROLE_SYSTEM_OPERATOR,
}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

MARKET_SEGMENTS = ["CORPORATE", "ASSOCIATION", "GOVERNMENT", "SMERF"]
LEAD_STATUSES = ["NEW", "QUALIFIED", "TURNED_DOWN", "DISPLACEMENT_REVIEW",
                 "CLEARED", "QUOTED", "WON", "LOST"]
ANALYSIS_VARIANTS = ["FORECAST_BASED", "HISTORICAL_BASED"]
ANALYSIS_STATUSES = ["PENDING", "APPROVED", "REJECTED"]
QUOTE_STATUSES = ["DRAFT", "PROPOSED", "COUNTERED", "ACCEPTED", "WITHDRAWN", "EXPIRED"]
CONTRACT_STATUSES = ["DRAFT", "SENT", "SIGNED", "COMPLETED", "CANCELLED",
                     "TERMINATED_FORCE_MAJEURE"]
ATTRITION_BASES = ["ROOM_NIGHTS", "PEAK_NIGHT"]
FORCE_MAJEURE_CLAUSES = ["NONE", "STANDARD", "EXPANDED"]
CANCELLATION_REASONS = ["CLIENT_CANCEL", "FORCE_MAJEURE"]
INVENTORY_STATUSES = ["SETUP", "OPEN", "CUT_OFF", "RELEASED", "CLOSED"]
BILLING_STATUSES = ["UNBILLED", "ATTRITION_ASSESSED", "WAIVED", "SETTLED"]
RESERVATION_STATUSES = ["PENDING", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT",
                        "CANCELLED", "NO_SHOW"]
RESERVATION_SOURCES = ["ROOMING_LIST", "INDIVIDUAL_CALL"]
CHARGE_CATEGORIES = ["BANQUET", "AUDIOVISUAL", "PARKING", "INTERNET"]
CHARGE_STATUSES = ["QUOTED", "POSTED", "VOIDED"]
RECONCILIATION_STATUSES = ["DRAFT", "FINALIZED", "SUPERSEDED"]
SPACE_CODES = ["GRAND_BALLROOM", "SALON_A", "SALON_B", "BOARDROOM"]
HOLD_STATUSES = ["HELD", "CONFIRMED", "RELEASED"]
DECISIONS = ["APPROVE", "REJECT"]

PICKUP_STATUSES = {"PENDING", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT"}
ACTUALIZED_STATUSES = {"CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "NO_SHOW"}


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

QUALIFICATION_FLOOR = 30
SEGMENT_MULTIPLIER = {
    "CORPORATE": Decimal("1.20"),
    "ASSOCIATION": Decimal("1.00"),
    "GOVERNMENT": Decimal("0.85"),
    "SMERF": Decimal("0.75"),
}
GROUP_RATE_FACTOR = Decimal("0.82")
ANCILLARY_PER_ROOM_NIGHT_CENTS = 4500
ATTRITION_DAMAGE_FACTOR = Decimal("0.85")
REBATE_CAP_PCT = Decimal("0.25")
SIZE_BONUS_PCT = Decimal("0.02")
SIZE_BONUS_FLOOR_CENTS = 2000000
INCENTIVE_RATE_CAP = Decimal("0.05")
FM_NO_CLAUSE_FACTOR = Decimal("0.50")
LAPSE_DAYS = 730
TURNOVER_MINUTES = 45
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Time / numeric helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_date_str(value):
    """Strict YYYY-MM-DD -> datetime.date, or None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_instant_str(value):
    """ISO 8601 UTC instant -> aware datetime, or None when malformed."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm, ss, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        dt = datetime(int(year), int(month), int(day), int(hh), int(mm),
                      int(ss or 0), micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return dt.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[0:2]), minutes=int(body[2:4])) * sign
    return (dt - offset).replace(tzinfo=timezone.utc)


def iso_instant(dt):
    """Render an aware datetime as an ISO 8601 UTC instant with 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    return d.isoformat()


def date_range(start, end):
    """Half-open [start, end) list of date objects."""
    out = []
    cur = start
    while cur < end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def whole_days(later, earlier):
    return (later - earlier).days


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal / int / float to the nearest whole unit, halves away from zero."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# In-memory store (empty on every boot -- nothing is ever seeded)
# ---------------------------------------------------------------------------

class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.accounts = {}
        self.leads = {}
        self.inventory_days = {}
        self.inventory_by_date = {}
        self.packages = {}
        self.analyses = {}
        self.quotes = {}
        self.contracts = {}
        self.blocks = {}
        self.nights = {}
        self.reservations = {}
        self.charges = {}
        self.reconciliations = {}
        self.holds = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- clock ------------------------------------------------------------
    def now(self):
        return self.clock

    def today(self):
        return self.clock.astimezone(timezone.utc).date()

    def now_iso(self):
        return iso_instant(self.clock)


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(extra=None):
    row = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "updated_at": store.now_iso(),
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Record a mutation on a persisted row: refresh updated_at, bump version."""
    if row is None:
        return
    row["updated_at"] = store.now_iso()
    row["version"] = row.get("version", 1) + 1


def in_order(rows):
    """Default ordering: created_at ascending, insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2 / SCAFFOLD §1.0)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": store.now_iso()}


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Authentication + role gate (validations priority 1 and 2)
# ---------------------------------------------------------------------------

def authenticate():
    uid = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if uid is None or not str(uid).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role names an unknown role.")
    return str(uid).strip(), role


def endpoint(roles):
    """Decorator running priority 1 (authentication) then priority 2 (role gate)
    before any body parsing, exactly as PRD §2.8 requires."""
    allowed = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = authenticate()
            if role not in allowed:
                fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def actor():
    return g.user_id


def actor_role():
    return g.role


def is_group_contact():
    return g.role == ROLE_GROUP_CONTACT


# ---------------------------------------------------------------------------
# Request schema validation (validations priority 3)
# ---------------------------------------------------------------------------

_MISSING = object()


def body_json():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
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


def _get(body, field):
    if field not in body:
        return _MISSING
    return body[field]


def v_int(body, field, required=True, minimum=None, maximum=None, default=None):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a JSON integer." % field)
    if minimum is not None and raw < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and raw > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, maximum))
    return raw


def v_number(body, field, required=True, minimum=None, maximum=None,
             exclusive_min=None, default=None):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a JSON number." % field)
    value = float(raw)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (field, exclusive_min))
    return value


def v_string(body, field, required=True, min_len=1, max_len=None, default=None,
             allow_blank=False):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if not allow_blank and not raw.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-blank." % field)
    if min_len is not None and len(raw) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % field)
    if max_len is not None and len(raw) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % field)
    return raw


def v_enum(body, field, allowed, required=True, default=None):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    if not isinstance(raw, str) or raw not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return raw


def v_bool(body, field, required=True, default=None):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    if not isinstance(raw, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a JSON boolean." % field)
    return raw


def v_date(body, field, required=True, default=None):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    parsed = parse_date_str(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % field)
    return parsed


def v_instant(body, field, required=True, default=None):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    parsed = parse_instant_str(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed


def v_id(body, field, required=True, default=None):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    if not isinstance(raw, str) or not raw.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-blank string." % field)
    return raw


def v_allotments(body, field="nightly_allotments", min_entries=1, max_entries=60):
    raw = _get(body, field)
    if raw is _MISSING or raw is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    if len(raw) < min_entries or len(raw) > max_entries:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must carry between %d and %d entries."
             % (field, min_entries, max_entries))
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST",
                 "Each '%s' entry must be an object." % field)
        stay = parse_date_str(entry.get("stay_date"))
        if stay is None:
            fail("ERR_INVALID_REQUEST",
                 "Each '%s' entry needs a YYYY-MM-DD stay_date." % field)
        rooms = entry.get("rooms")
        if isinstance(rooms, bool) or not isinstance(rooms, int):
            fail("ERR_INVALID_REQUEST",
                 "Each '%s' entry needs an integer rooms count." % field)
        if rooms < 1:
            fail("ERR_INVALID_REQUEST",
                 "Each '%s' entry needs rooms >= 1." % field)
        out.append({"stay_date": stay, "rooms": rooms})
    return out


def check_contiguous_distinct(entries):
    """validations priority 7: distinct and contiguous stay_date values."""
    dates = [e["stay_date"] for e in entries]
    if len(set(dates)) != len(dates):
        fail("ERR_INVALID_DATE_RANGE", "Allotment plan carries a duplicate stay_date.")
    ordered = sorted(dates)
    for index in range(1, len(ordered)):
        if (ordered[index] - ordered[index - 1]).days != 1:
            fail("ERR_INVALID_DATE_RANGE", "Allotment plan is not contiguous.")


# ---------------------------------------------------------------------------
# Query parameter validation (validations priority 3)
# ---------------------------------------------------------------------------

def q_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        if not re.match(r"^-?\d+$", limit_raw.strip()):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None:
        if not re.match(r"^-?\d+$", offset_raw.strip()):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        offset = int(offset_raw)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def q_date(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    parsed = parse_date_str(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be a YYYY-MM-DD date." % name)
    return parsed


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be true or false." % name)


def q_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
