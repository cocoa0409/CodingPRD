"""In-memory store, logical clock, id/time helpers and domain constants.

State is held entirely in Python dicts. Nothing is persisted to disk, so a fresh
process (one per test under --isolation per-test-server) always starts empty.
No entity is ever seeded here.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# --- §2.5 the logical hall clock -------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# --- day/hour denominated constants (§2.5, §1.3) ---------------------------
ACCEPTANCE_WINDOW_HOURS = 24
RESIGN_INTERVAL_DAYS = 30
RECALL_WINDOW_DAYS = 7
LAYOFF_REREG_WINDOW_DAYS = 5
GRIEVANCE_FILING_WINDOW_DAYS = 10
RETENTION_DAYS = 1825
SHORT_CALL_MAX_DAYS = 5
REFUSAL_WINDOW_DAYS = 365
REFUSALS_BEFORE_REMOVAL = 3
REREGISTRATION_COOLDOWN_DAYS = 30

# --- allowance / ratio / money constants -----------------------------------
NAMED_CALL_DIVISOR = 5
NAMED_CALL_HARD_CAP = 4
SPECIAL_SKILL_SHARE_BP = 5000
STANDARD_DAY_HOURS = 8
BASIS_POINT_SCALE = 10000
JOURNEYWORKER_RATE_FACTOR_BP = 10000
APPRENTICE_RATE_FACTOR_BP = {1: 5625, 2: 6875, 3: 8125, 4: 9375}

# --- enums -----------------------------------------------------------------
ROLES = ("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep", "Member")
LOCAL_KINDS = ("HOME", "SISTER")
CLASSIFICATIONS = ("JOURNEYWORKER", "APPRENTICE")
STANDINGS = ("GOOD_STANDING", "DELINQUENT")
SKILL_CODES = ("WELDING_6G", "RIGGING", "INSTRUMENTATION", "FIRE_WATCH")
GROUP_CODES = ("GROUP_1", "GROUP_2", "GROUP_3", "GROUP_4")
ORDERING_POLICIES = ("SENIORITY", "FIRST_REGISTERED")
REGISTRATION_STATUSES = ("REGISTERED", "REFERRED", "DISPATCHED_OUT", "REMOVED", "EXPIRED")
REMOVAL_REASONS = ("THREE_REFUSALS", "VOLUNTARY", "ADMINISTRATIVE", "RENEWAL_LAPSED")
MANUAL_REMOVAL_REASONS = ("VOLUNTARY", "ADMINISTRATIVE")
SIGNATORY_STATUSES = ("SIGNATORY", "DELINQUENT_TRUST_FUNDS", "TERMINATED")
DURATION_TYPES = ("SHORT_CALL", "LONG_CALL")
JOB_REQUEST_STATUSES = ("OPEN", "PARTIALLY_FILLED", "FILLED", "SUSPENDED", "CLOSED", "CANCELLED")
SLOT_KINDS = ("JOURNEYWORKER", "APPRENTICE")
REFERRAL_KINDS = ("LIST_ORDER", "NAMED_CALL", "SPECIAL_SKILL")
VARIANTS = ("STRICT_GROUP_ORDER", "SHORT_CALL_INTERFILED", "NOT_APPLICABLE")
GOOD_CAUSE_CODES = ("MEDICAL", "TEMPORARILY_EMPLOYED", "OUT_OF_AREA_TRAVEL")
REFERRAL_STATUSES = ("ISSUED", "ACCEPTED", "REFUSED", "EXPIRED", "WITHDRAWN")
LAYOFF_REASONS = ("REDUCTION_IN_FORCE", "JOB_COMPLETE", "LACK_OF_WORK", "FOR_CAUSE", "QUIT")
NO_FAULT_LAYOFF_REASONS = ("REDUCTION_IN_FORCE", "JOB_COMPLETE", "LACK_OF_WORK")
DISPATCH_STATUSES = ("WORKING", "LAID_OFF", "TERMINATED_FOR_CAUSE", "QUIT")
CLAIM_TYPES = ("OUT_OF_ORDER_DISPATCH", "IMPROPER_NAMED_CALL", "RATIO_VIOLATION", "RECORD_UNAVAILABLE")
DECISIONS = ("SUSTAINED", "DENIED")
REMEDIES = ("NONE", "MAKE_WHOLE_HOURS", "NEXT_AVAILABLE_PRIORITY")
BACK_PAY_VARIANTS = ("ACTUAL_HOURS", "SCHEDULED_HOURS", "NOT_APPLICABLE")
GRIEVANCE_STATUSES = ("FILED", "UNDER_REVIEW", "SUSTAINED", "DENIED")
POLICY_STATUSES = ("ACTIVE", "SUPERSEDED")
PURGE_STATES = ("RETAINED", "PURGED")
EVENT_CODES = (
    "REGISTRATION_CREATED", "REGISTRATION_RENEWED", "REGISTRATION_REMOVED",
    "REGISTRATION_EXPIRED", "REFERRAL_ISSUED", "REFERRAL_ACCEPTED",
    "REFERRAL_REFUSED", "REFERRAL_EXPIRED", "REFERRAL_WITHDRAWN",
    "DISPATCH_LAID_OFF", "DISPATCH_RECALLED", "GRIEVANCE_DECIDED",
    "MAKE_WHOLE_CREDITED", "POSITION_RESTORED",
)


class Store(object):
    """Every collection is a plain dict keyed by id. Reset on process start."""

    def __init__(self):
        self.locals = {}
        self.members = {}
        self.endorsements = {}
        self.lists = {}
        self.registrations = {}
        self.contractors = {}
        self.job_requests = {}
        self.referrals = {}
        self.dispatches = {}
        self.grievances = {}
        self.ledger = {}
        self.ratio_policies = {}
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def seq(self):
        return next(self._counter)


db = Store()


def now():
    """The logical hall clock. Never wall-clock time."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    # Truncate to millisecond precision so stored instants render byte-identically.
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)


def round_half_up_div(numerator, denominator=BASIS_POINT_SCALE):
    """Integer round-half-up of numerator/denominator (denominator > 0)."""
    if numerator >= 0:
        return (numerator * 2 + denominator) // (denominator * 2)
    return -((-numerator * 2 + denominator) // (denominator * 2))


def touch(record):
    """Refresh updated_at and bump version on a mutation (§2.4)."""
    record["updated_at"] = db.clock
    record["version"] = record.get("version", 1) + 1
