"""Benchmark-wide constants, read from PRD 2/3 and SCAFFOLD Table 3."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone


def d(value):
    """Decimal from anything numeric (never float arithmetic for money)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to an integer, half away from zero (PRD 2.4)."""
    return int(d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    """Four decimal places, round half up (PRD 2.4)."""
    return float(d(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# --- pricing engine -------------------------------------------------------
MIN_MILES = 50
MIN_RATE_FLOOR_CENTS = 50000
MIN_RATE_FLOOR_MULTIPLE = Decimal("0.85")
LANE_INDEX_MODULUS = 11
LANE_INDEX_STEP = Decimal("20")

MARKET_LEVEL_CENTS_PER_MILE = {
    "DRY_VAN": {"OPEN": 210, "BALANCED": 235, "TIGHT": 275},
    "REEFER": {"OPEN": 250, "BALANCED": 285, "TIGHT": 330},
    "FLATBED": {"OPEN": 230, "BALANCED": 260, "TIGHT": 305},
}

WEIGHT_ADJUSTMENT = {
    "DRY_VAN": (40000, Decimal("0.02")),
    "REEFER": (40000, Decimal("0.03")),
    "FLATBED": (None, Decimal("0.00")),
}

COMMODITY_MULTIPLE = {
    "GENERAL": Decimal("1.00"),
    "TEMPERATURE_CONTROLLED": Decimal("1.15"),
    "HAZMAT": Decimal("1.25"),
    "HIGH_VALUE": Decimal("1.20"),
}

LOCK_WINDOW_MINUTES = 60
LATE_BOOKING_SURCHARGE_PCT = Decimal("0.05")

# --- quotes ---------------------------------------------------------------
QUOTE_TTL_HOURS = 24

# --- risk -----------------------------------------------------------------
RISK_BREACH_PENALTY = 8
RISK_CLAIM_PENALTY = 12
RISK_CLAWBACK_PENALTY = 5
RISK_ELIGIBILITY_FLOOR = Decimal("40.0")
RISK_SLACK_MINUTES_PER_POINT = Decimal("2.4")

# --- appointments / docks -------------------------------------------------
DOCK_BUFFER_MINUTES = 120
MISSED_GRACE_MINUTES = 60
COVERAGE_HORIZON_HOURS = 24

# --- booking window -------------------------------------------------------
EQUIPMENT_BUFFER_MINUTES = 0

# --- breach / claims ------------------------------------------------------
TOLERANCE_MINUTES = 30
TRUCKLOAD_WEIGHT_LBS = 44000
PRICE_CAP_MULTIPLIER = Decimal("1.5")
MAX_REVIEW_ROUNDS = 3
ESCALATION_THRESHOLD_CENTS = 2500000
COMMODITY_LIABILITY_CAP = {
    "GENERAL": 100000000,
    "TEMPERATURE_CONTROLLED": 100000000,
    "HAZMAT": 100000000,
    "HIGH_VALUE": 250000000,
}

# --- settlements ----------------------------------------------------------
QUICK_PAY_TIERS = [
    (0, 4, Decimal("0.0300")),
    (5, 19, Decimal("0.0250")),
    (20, 49, Decimal("0.0200")),
    (50, None, Decimal("0.0150")),
]

# --- carrier onboarding floors -------------------------------------------
MIN_INSURANCE_LIABILITY_CENTS = 75000000
MIN_CARGO_COVERAGE_CENTS = 100000000
MAX_SAFETY_SCORE = Decimal("80.0")

# --- enums ----------------------------------------------------------------
ROLES = [
    "Anonymous", "Shipper", "Carrier", "ComplianceReviewer", "ClaimsAdjuster", "PlatformAdmin",
]

PRICING_MODES = ["SPOT", "CONTRACT"]
MARKET_BANDS = ["OPEN", "BALANCED", "TIGHT"]
EQUIPMENT_TYPES = ["DRY_VAN", "REEFER", "FLATBED"]
COMMODITIES = ["GENERAL", "TEMPERATURE_CONTROLLED", "HAZMAT", "HIGH_VALUE"]
SLOT_KINDS = ["PICKUP", "DELIVERY"]
REPORTED_STATUSES = ["EN_ROUTE_PICKUP", "AT_PICKUP", "IN_TRANSIT", "AT_DELIVERY", "DELIVERED"]
STATUS_RANKS = {
    "EN_ROUTE_PICKUP": 1,
    "AT_PICKUP": 2,
    "IN_TRANSIT": 3,
    "AT_DELIVERY": 4,
    "DELIVERED": 5,
}
STATUS_EVENT_TYPES = [
    "BOOKED", "POSTED", "UNCOVERED", "DISPATCHED", "ARRIVED_PICKUP",
    "DEPARTED_PICKUP", "ARRIVED_DELIVERY", "DELIVERED", "EXCEPTION",
]
FILED_BY_ROLES = ["SHIPPER", "CARRIER"]
PAYOUT_MODES = ["TERMS", "QUICK_PAY"]
WAIVE_REASONS = ["FACILITY_FAULT", "FORCE_MAJEURE", "GOODWILL"]
EQUIPMENT_STATUSES = ["AVAILABLE", "ASSIGNED", "IN_SHOP"]

TERMINAL_LOAD_STATES = ["PAID", "CANCELLED", "VOIDED"]
CONTRACT_DRAW_STATES = ["BOOKED", "IN_TRANSIT", "DELIVERED", "INVOICED", "PAID"]


def utc(instant):
    if instant.tzinfo is None:
        return instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def plus_minutes(instant, minutes):
    return utc(instant) + timedelta(minutes=minutes)


def plus_hours(instant, hours):
    return utc(instant) + timedelta(hours=hours)


def plus_days(instant, days):
    return utc(instant) + timedelta(days=days)


def minutes_between(later, earlier):
    return int((utc(later) - utc(earlier)).total_seconds() // 60)


def parse_instant(value, field="datetime"):
    """Accept an ISO 8601 instant; raise ERR_INVALID_REQUEST when malformed."""
    from errors import ApiError
    if isinstance(value, datetime):
        return utc(value)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % field)
    return utc(parsed)