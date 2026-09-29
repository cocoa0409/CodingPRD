"""In-memory store, logical clock and identity helpers.

Everything lives in module level dicts.  There is deliberately no seeding: a
fresh process starts with an entirely empty system and tests build all state
through the declared endpoints.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from errors import fail

# --------------------------------------------------------------------------
# constants (PRD section 2 / SCAFFOLD global_constants)
# --------------------------------------------------------------------------
SERVER_START_CLOCK_UTC = "2026-08-01T00:00:00Z"
LATE_REPORT_LIMIT_HOURS = 168
CORRECTION_CONFIRM_WINDOW_HOURS = 72
MIN_RECLAIM_HOURS = 24
RECLAIM_FILING_WINDOW_DAYS = 60
DETENTION_SPLIT_PCT = "0.5"
REVERSE_ROUTE_PENALTY_PCT = "0.25"
REPAIR_LABOR_RATE_CENTS_PER_HOUR = 9500
REPAIR_HANDLING_FEE_PCT = "0.075"
REPAIR_PREAUTH_THRESHOLD_CENTS = 150000
FEE_TIER_BREAK_CENTS = 500000
FEE_TIER1_PCT = "0.005"
FEE_TIER2_PCT = "0.0035"
MAX_DISPUTE_ROUNDS = 3
MAX_COUNTER_BILL_ROUNDS = 2
DISPUTE_WINDOW_DAYS = 30
REOPEN_WINDOW_DAYS = 30
PROJECTION_HORIZON_HOURS = 72
DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS = 100000000

# --------------------------------------------------------------------------
# roles (PRD section 2.1)
# --------------------------------------------------------------------------
ROLE_ADMIN = "ClearinghouseAdmin"
ROLE_CLERK = "InterchangeClerk"
ROLE_ACCOUNTANT = "CarHireAccountant"
ROLE_REPAIR_AGENT = "RepairBillingAgent"
ROLE_FLEET_OWNER = "FleetOwner"

ALL_ROLES = [ROLE_ADMIN, ROLE_CLERK, ROLE_ACCOUNTANT, ROLE_REPAIR_AGENT, ROLE_FLEET_OWNER]
ENTITY_BACKED_ROLES = [ROLE_CLERK, ROLE_ACCOUNTANT, ROLE_REPAIR_AGENT, ROLE_FLEET_OWNER]

HEADER_ROLE = "X-User-Role"
HEADER_USER = "X-User-ID"

# --------------------------------------------------------------------------
# enumerations
# --------------------------------------------------------------------------
RAILROAD_STATUS = ["ACTIVE", "SUSPENDED"]
JUNCTION_STATUS = ["OPEN", "CLOSED"]
TIME_COMPONENT_MODE = ["PER_DIEM", "HOURLY"]
CUSTODY_STATUS = ["ON_HOME_ROAD", "ON_FOREIGN_ROAD"]
MECHANICAL_STATUS = ["SERVICEABLE", "BAD_ORDER", "UNDER_REPAIR"]
ROUTING_STATUS = ["NO_OBLIGATION", "OBLIGATION_ACTIVE", "OBLIGATION_MET", "OBLIGATION_VIOLATED"]
EVENT_TYPE = ["INTERCHANGE_DELIVERY", "INTERCHANGE_REJECTION"]
EVENT_STATUS = ["RECORDED", "SUPERSEDED", "VOID"]
EVENT_SOURCE = ["CLERK_CAPTURE", "CORRECTION_APPLY"]
LOAD_STATUS = ["LOADED", "EMPTY"]
MOVEMENT_STATUS = ["OPEN", "CLOSED", "VOID"]
RECLAIM_REASON = ["BAD_ORDER", "EMBARGO", "CUSTOMER_DETENTION"]
RECLAIM_STATUS = ["FILED", "ALLOWED", "DISALLOWED", "WITHDRAWN"]
EMBARGO_STATUS = ["ACTIVE", "LIFTED"]
DEFECT_CLASS = ["HANDLING_DAMAGE", "NORMAL_WEAR", "OWNER_APPLIANCE_DEFECT"]
REPAIR_BILL_STATUS = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "SETTLED"]
RESPONSIBILITY_RULE = ["HANDLING_LINE_RULE", "OWNER_RESPONSIBILITY_RULE"]
CYCLE_STATUS = ["OPEN", "COMPUTED", "EXCHANGED", "SETTLED", "REOPENED", "ARCHIVED"]
STATEMENT_VARIANT = ["AS_REPORTED", "RECONCILED"]
DISPUTE_REASON = [
    "HIRE_RATE_MISAPPLIED",
    "MILEAGE_DISCREPANCY",
    "RECLAIM_DENIED_IMPROPERLY",
    "REPAIR_RESPONSIBILITY",
    "DUPLICATE_CHARGE",
]
DISPUTE_STATUS = ["OPEN", "COUNTERED", "ACCEPTED", "WITHDRAWN"]
CORRECTION_TYPE = ["MISSED_EVENT_INSERT", "TIMESTAMP_AMEND", "ERRONEOUS_EVENT_VOID"]
CORRECTION_DIRECTION = ["FILER_DELIVERS", "FILER_RECEIVES"]
CORRECTION_STATUS = ["FILED", "CONFIRMED", "REJECTED", "APPLIED", "EXPIRED"]
LEDGER_ENTRY_TYPE = [
    "HIRE_CHARGE",
    "REPAIR_CHARGE",
    "RECLAIM_CREDIT",
    "RECLAIM_REVERSAL",
    "CORRECTION_ADJUSTMENT",
    "DISPUTE_ADJUSTMENT",
    "RECOMPUTE_REVERSAL",
    "SETTLEMENT_PAYMENT",
]
EXPOSURE_VARIANT = ["SNAPSHOT", "PROJECTED"]

# --------------------------------------------------------------------------
# stores
# --------------------------------------------------------------------------
railroads = {}
junctions = {}
car_types = {}
cars = {}
events = {}
movements = {}
claims = {}
embargoes = {}
bills = {}
cycles = {}
disputes = {}
corrections = {}
ledger = {}

STORES = {
    "railroad": (railroads, "ERR_RAILROAD_NOT_FOUND"),
    "junction": (junctions, "ERR_JUNCTION_NOT_FOUND"),
    "car_type": (car_types, "ERR_CAR_TYPE_NOT_FOUND"),
    "car": (cars, "ERR_CAR_NOT_FOUND"),
    "event": (events, "ERR_INTERCHANGE_EVENT_NOT_FOUND"),
    "movement": (movements, "ERR_MOVEMENT_NOT_FOUND"),
    "claim": (claims, "ERR_RECLAIM_CLAIM_NOT_FOUND"),
    "embargo": (embargoes, "ERR_EMBARGO_ORDER_NOT_FOUND"),
    "bill": (bills, "ERR_REPAIR_BILL_NOT_FOUND"),
    "cycle": (cycles, "ERR_SETTLEMENT_CYCLE_NOT_FOUND"),
    "dispute": (disputes, "ERR_DISPUTE_NOT_FOUND"),
    "correction": (corrections, "ERR_CORRECTION_REQUEST_NOT_FOUND"),
    "ledger_entry": (ledger, "ERR_LEDGER_ENTRY_NOT_FOUND"),
}

_seq = itertools.count(1)

# --------------------------------------------------------------------------
# logical clock (PRD section 2.4)
# --------------------------------------------------------------------------


def parse_instant(text):
    """Parse an ISO-8601 instant.  Returns a tz-aware UTC datetime or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_clock = {"now": parse_instant(SERVER_START_CLOCK_UTC)}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def iso(dt):
    """ISO-8601 UTC with exactly three fractional digits (PRD section 2.2)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    row = {"id": new_id(), "created_at": now(), "_seq": next(_seq)}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Register a mutation: refresh updated_at and bump version."""
    if "version" in row:
        row["updated_at"] = now()
        row["version"] = row["version"] + 1
    return row


def lookup(kind, value):
    store, err = STORES[kind]
    if not isinstance(value, str) or value not in store:
        fail(err)
    return store[value]


def find(kind, value):
    store, _ = STORES[kind]
    if not isinstance(value, str):
        return None
    return store.get(value)


def order_key(row):
    return (row["created_at"], row["_seq"])
