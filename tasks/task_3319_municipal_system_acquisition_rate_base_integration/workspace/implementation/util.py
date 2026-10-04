import uuid
from datetime import datetime, timezone, timedelta

# Logical clock: starts at exactly 2026-09-01T00:00:00Z, only advances via
# POST /_clock/set_current_utc. Never falls back to wall-clock time.
_logical_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# PRD section 3 constants (read from SCAFFOLD.yaml calculations table).
PLANNING_CONTINGENCY = 0.10
FILING_CONTINGENCY = 0.15
PREMIUM_CAP_RATE = 0.10
COUNCIL_PASS_PCT = 60.00
REFERENDUM_TRIGGER_PCT = 50.00
REFERENDUM_PASS_PCT = 50.00
MAX_CREWS_PER_TARGET = 3
MIN_HEARING_NOTICE_DAYS = 7
PHASE_IN_CAP_PCT = 5

ALL_ROLES = [
    "AcquisitionAnalyst", "EngineeringReviewer", "Appraiser", "MunicipalClerk",
    "RegulatoryOfficer", "Commissioner", "TransitionManager", "HRDirector",
    "SystemAdmin",
]

TARGET_STATUSES = [
    "SCREENING", "VALUATION", "MUNICIPAL_REVIEW", "REGULATORY_REVIEW",
    "CLOSING", "INTEGRATED", "REJECTED",
]
TERMINAL_TARGET_STATUSES = ["REJECTED", "INTEGRATED"]

VALUATION_METHODS = ["FMV_INDEPENDENT", "REPLACEMENT_COST", "ORIGINAL_COST_LESS_DEPRECIATION"]
SYSTEM_TYPES = ["WATER", "WASTEWATER", "COMBINED"]
CAPITAL_CATEGORIES = ["DISTRIBUTION", "COLLECTION", "TREATMENT", "SOURCE", "STORAGE", "GENERAL"]
CAPITAL_HORIZONS = ["IMMEDIATE", "SHORT_TERM", "LONG_TERM"]
EVENT_KINDS = ["PUBLIC_HEARING", "COUNCIL_VOTE", "REFERENDUM"]
RATE_BASE_METHODS = ["AS_PAID", "DEPRECIATED_ORIGINAL_COST"]
TARIFF_MODES = ["SINGLE_TARIFF", "STAND_ALONE"]
OFFER_RESPONSES = ["ACCEPTED", "DECLINED", "ASSUMED"]

TRANSITION_ITEM_ORDER = ["BILLING_RECORDS", "DEPOSITS", "SERVICE_AGREEMENTS", "METER_READS"]


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Server timestamp for created_at/updated_at: wall-clock UTC, ISO 8601 with 3 fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_logical_clock():
    return _logical_clock.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_logical_clock.microsecond // 1000:03d}Z"


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def request_id():
    return "req_" + uuid.uuid4().hex[:20]


def hearing_notice_deadline(scheduled_end):
    return scheduled_end + timedelta(days=MIN_HEARING_NOTICE_DAYS)
