"""Core primitives: in-memory store, logical clock, response envelope, errors."""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Calculation constants (PRD section 3 / SCAFFOLD calculations)
# ---------------------------------------------------------------------------
RECONDITION_BUFFER_DAYS = 2
MIN_RENTAL_DAYS = 3
MAX_RENTAL_DAYS = 14

REFERENCE_REVENUE_PER_TURN_CENTS = 3200
PROJECTED_SERVICING_PER_TURN_CENTS = 2000

W_CLAIM_RATE = Decimal("0.5")
W_SEVERITY = Decimal("0.3")
W_LATE = Decimal("0.2")
SEVERITY_WEIGHT = {"MINOR": 1, "MODERATE": 2, "SEVERE": 3, "LOSS": 4}
BAND_LOW_MAX = 20
BAND_ELEVATED_MAX = 49

RESIDUAL_RATE_BY_GRADE = {
    "A": Decimal("0.55"),
    "B": Decimal("0.40"),
    "C": Decimal("0.25"),
    "D": Decimal("0.10"),
}
SEVERITY_BASE_CENTS = {"MINOR": 2500, "MODERATE": 9000, "SEVERE": 22000}
SEVERITY_PCT = {
    "MINOR": Decimal("0.10"),
    "MODERATE": Decimal("0.35"),
    "SEVERE": Decimal("0.75"),
    "LOSS": Decimal("1.00"),
}
MAX_DISPUTE_ROUNDS = 2
DISPUTE_WINDOW_DAYS = 7

RESALE_RATE_BY_GRADE = {
    "A": Decimal("0.45"),
    "B": Decimal("0.32"),
    "C": Decimal("0.20"),
    "D": Decimal("0.08"),
}
MARKDOWN_STEP_PCT = Decimal("0.15")
MAX_MARKDOWN_STEPS = 3
TIER_MID_FLOOR_CENTS = 5000
TIER_HIGH_FLOOR_CENTS = 20000
CHANNEL_FEE_PCT = {
    "OUTLET": {"LOW": Decimal("0.05"), "MID": Decimal("0.08"), "HIGH": Decimal("0.12")},
    "PARTNER_RESALE": {"LOW": Decimal("0.15"), "MID": Decimal("0.18"), "HIGH": Decimal("0.22")},
}
CHANNEL_HANDLING_CENTS = {"OUTLET": 400, "PARTNER_RESALE": 900}
MIN_NET_RECOVERY_CENTS = 2000
MAX_SALE_DISCOUNT_PCT = Decimal("0.10")
LISTING_WINDOW_DAYS = 30

CLEANING_COST_CENTS = {"NONE": 0, "LIGHT": 1200, "HEAVY": 2600}
REPAIR_COST_CENTS = {"NONE": 0, "MINOR": 1500, "MODERATE": 4200, "SEVERE": 9800, "LOSS": 0}
PHOTOGRAPHY_COST_CENTS = 800
REPAIR_ATTEMPT_CAP = 2

RETURN_GRACE_DAYS = 2
LATE_FEE_PER_DAY_CENTS = 500
LATE_FEE_CAP_CENTS = 5000

DAYS_PER_PLANNING_MONTH = 30
REPLENISH_TRIGGER_UNITS = 1

FIT_DELTA = {
    "TOO_SMALL": -2,
    "SLIGHTLY_SMALL": -1,
    "TRUE_TO_SIZE": 0,
    "SLIGHTLY_LARGE": 1,
    "TOO_LARGE": 2,
}
FIT_BASELINE = 50
KEEP_INTENT_BONUS = 5

DELINQUENCY_THRESHOLD_CENTS = 15000
SHIPMENT_EXCEPTION_CAP = 2

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
SIZES = ["XS", "S", "M", "L", "XL"]
CATEGORIES = ["GOWN", "BLAZER", "DRESS", "KNITWEAR", "ACCESSORY"]
CONDITION_GRADES = ["A", "B", "C", "D"]
TECH_STATUSES = ["ACTIVE", "SUSPENDED"]
UNIT_AVAILABILITY = ["IN_STOCK", "RESERVED", "OUT", "INBOUND", "PROCESSING", "RETIRED", "SOLD"]
UNIT_CONDITION = ["FLOOR_READY", "NEEDS_CLEANING", "NEEDS_REPAIR", "QUARANTINED", "CONDEMNED"]
RETIREMENT_REASONS = ["TURNS_EXHAUSTED", "CONDEMNED_DAMAGE", "LOSS", "PLANNED_REFRESH"]
MEMBER_STATUSES = ["ACTIVE", "PAUSED", "DELINQUENT", "CANCELLED"]
RESERVATION_STATES = [
    "REQUESTED", "MATCHED", "WAITLISTED", "SHIPPED", "IN_POSSESSION",
    "RETURN_INITIATED", "RETURNED", "CLOSED", "RELEASED", "CANCELLED", "SUPERSEDED",
]
RESERVATION_TERMINAL = {"CLOSED", "RELEASED", "CANCELLED", "SUPERSEDED"}
SHIPMENT_DIRECTIONS = ["OUTBOUND", "INBOUND"]
SHIPMENT_STATES = ["CREATED", "IN_TRANSIT", "EXCEPTION", "DELIVERED", "RECEIVED"]
SHIPMENT_TERMINAL = {"DELIVERED", "RECEIVED"}
JOB_STATES = [
    "RECEIVED", "INSPECTED", "PROCESSING", "READY_FOR_PHOTO",
    "PHOTOGRAPHED", "RESTOCKED", "CONDEMNED_HOLD",
]
JOB_TERMINAL = {"RESTOCKED"}
SOIL_LEVELS = ["NONE", "LIGHT", "HEAVY"]
DAMAGE_SEVERITIES = ["NONE", "MINOR", "MODERATE", "SEVERE", "LOSS"]
CLAIM_SEVERITIES = ["MINOR", "MODERATE", "SEVERE", "LOSS"]
CLAIM_STATES = ["OPEN", "ASSESSED", "DISPUTED", "CHARGED", "WAIVED", "DISMISSED"]
CLAIM_TERMINAL = {"WAIVED", "DISMISSED"}
RESOLUTIONS = ["UPHELD", "OVERTURNED", "PARTIAL"]
CHANNELS = ["OUTLET", "PARTNER_RESALE"]
LISTING_STATES = ["DRAFT", "LISTED", "EXPIRED", "SOLD", "WITHDRAWN"]
LISTING_TERMINAL = {"SOLD", "WITHDRAWN"}
FIT_RATINGS = ["TOO_SMALL", "SLIGHTLY_SMALL", "TRUE_TO_SIZE", "SLIGHTLY_LARGE", "TOO_LARGE"]
LEDGER_KINDS = ["DAMAGE_FEE", "LATE_FEE", "WAIVER_CREDIT", "SETTLEMENT_PAYMENT", "DISPUTE_REVERSAL"]
LEDGER_DIRECTIONS = ["DEBIT", "CREDIT"]
REPAIR_OUTCOMES = ["ACCEPTED", "FAILED"]
RISK_VARIANTS = ["LIFETIME", "ROLLING_12M"]
ECON_VARIANTS = ["REALIZED", "PROJECTED"]

ROLES = ["Member", "WarehouseTech", "ClaimsAdjuster", "InventoryPlanner", "PlatformAdmin"]

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "membership_plans", "technicians", "styles", "rental_units", "members",
    "reservations", "shipments", "reverse_logistics_jobs", "inspections",
    "damage_claims", "resale_listings", "fit_feedbacks", "fee_ledger_entries",
]

DB = {name: {} for name in COLLECTIONS}
_SEQ = {"n": 0}
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def reset_store():
    for name in COLLECTIONS:
        DB[name] = {}
    _SEQ["n"] = 0
    CLOCK["now"] = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return CLOCK["now"]


def fmt_ts(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(CLOCK["now"])


def today_str():
    return CLOCK["now"].astimezone(timezone.utc).strftime("%Y-%m-%d")


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def date_add(s, days):
    return (parse_date(s) + timedelta(days=days)).strftime("%Y-%m-%d")


def date_diff(a, b):
    """days(a) - days(b) where a and b are YYYY-MM-DD strings."""
    return (parse_date(a) - parse_date(b)).days


def is_date_str(s):
    if not isinstance(s, str) or len(s) != 10:
        return False
    try:
        parse_date(s)
        return True
    except Exception:
        return False


def parse_instant(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def rhu(value):
    """Round half up, away from zero, to an integer number of cents."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ACTOR_NOT_FOUND": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_STYLE_NOT_FOUND": 404,
    "ERR_RENTAL_UNIT_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_FEE_ENTRY_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_STALE_MEMBER_VERSION": 412,
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_RESOURCE_TERMINAL": 409,
    "ERR_QUARANTINE_HOLD_ACTIVE": 409,
    "ERR_UNIT_CONDEMNED": 409,
    "ERR_OPEN_CLAIM_BLOCKS_RESTOCK": 409,
    "ERR_REPAIR_PENDING": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TECHNICIAN_NOT_CERTIFIED": 403,
    "ERR_TECHNICIAN_SUSPENDED": 403,
    "ERR_REPAIR_ATTEMPTS_EXHAUSTED": 409,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_SIZE_NOT_IN_SIZE_RUN": 422,
    "ERR_UNIT_NOT_ALLOCATABLE": 409,
    "ERR_UNIT_TURNS_EXHAUSTED": 409,
    "ERR_INVALID_SUPERSEDE_TARGET": 422,
    "ERR_LISTING_ALREADY_ACTIVE": 409,
    "ERR_FEEDBACK_NOT_ELIGIBLE": 409,
    "ERR_FEEDBACK_ALREADY_EXISTS": 409,
    "ERR_SHIPMENT_EXCEPTION_CAP_REACHED": 409,
    "ERR_SHIPMENT_ALREADY_EXISTS": 409,
    "ERR_INVALID_RENTAL_WINDOW": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_UNIT_WINDOW_COLLISION": 409,
    "ERR_SHIPPING_CADENCE_COLLISION": 409,
    "ERR_LISTING_WINDOW_OPEN": 409,
    "ERR_UNIT_HAS_ACTIVE_COMMITMENT": 409,
    "ERR_UNIT_NOT_RETIRED": 409,
    "ERR_ITEM_SLOTS_EXHAUSTED": 409,
    "ERR_SWAP_ALLOWANCE_EXHAUSTED": 409,
    "ERR_WAIVER_NOT_AVAILABLE": 409,
    "ERR_NOTHING_TO_CHARGE": 409,
    "ERR_SETTLEMENT_EXCEEDS_BALANCE": 422,
    "ERR_SALE_PRICE_BELOW_FLOOR": 422,
    "ERR_OUTSTANDING_BALANCE": 409,
    "ERR_UNITS_STILL_OUT": 409,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize()


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
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
