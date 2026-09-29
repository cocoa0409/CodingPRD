"""In-memory store, logical clock and numeric helpers.

Storage is process-local only: every re-invocation of start.sh boots an empty store.
NOTHING is seeded here — tests build every entity through the declared API surface.
"""
import datetime as _dt
import itertools
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
ROLES = (
    "CteDirector",
    "StateComplianceReviewer",
    "GrantFiscalOfficer",
    "CommitteeChair",
    "SchoolRegistrar",
)

CLNA_VALIDITY_DAYS = 730
LABOR_MARKET_DATA_MAX_AGE_DAYS = 730
CLNA_STAKEHOLDER_MEETINGS_MIN = 2

MIN_SECONDARY_CREDITS = Decimal("4.0")
ARTICULATION_FLOOR = Decimal("3.0")
DEPTH_WEIGHT = Decimal("0.60")
BRIDGE_WEIGHT = Decimal("0.30")
BREADTH_BONUS = Decimal("0.10")
ALIGNMENT_APPROVAL_FLOOR = Decimal("0.7500")

CONCENTRATOR_CREDIT_MIN = Decimal("2.0")

SMALL_COHORT_MIN = 5
PERFORMANCE_TOLERANCE = Decimal("0.90")
MISS_TOLERANCE = 2
MAX_NEGOTIATION_ROUNDS = 4
MAX_PLAN_REVISION_ROUNDS = 3
MIN_PLAN_MILESTONES = 3

FEDERAL_SHARE_BY_CATEGORY = {
    "EQUIPMENT": Decimal("0.8500"),
    "CONSUMABLE": Decimal("0.8500"),
    "PROFESSIONAL_DEVELOPMENT": Decimal("1.0000"),
    "ADMINISTRATION": Decimal("0.8500"),
    "ENTERTAINMENT": Decimal("0.0000"),
}
CAPITAL_THRESHOLD_CENTS = 500000
CAPITAL_REVIEW_WINDOW_DAYS = 365

INDIRECT_RATE_TIER_1 = Decimal("0.0812")
INDIRECT_RATE_TIER_2 = Decimal("0.0650")
INDIRECT_RATE_TIER_3 = Decimal("0.0500")
INDIRECT_TIER_1_CEILING = 5000000
INDIRECT_TIER_2_CEILING = 20000000
ADMIN_CAP_PCT = Decimal("0.05")

ASSET_BUFFER_DAYS = 14

CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------- enums
CLUSTERS = ("HEALTH_SCIENCE", "ADVANCED_MANUFACTURING", "INFORMATION_TECHNOLOGY",
            "CONSTRUCTION", "AGRICULTURE")
APPROVAL_STATUSES = ("DRAFT", "SUBMITTED", "COMMITTEE_REVIEW", "CHANGES_REQUESTED",
                     "STATE_APPROVED", "SUSPENDED")
CLNA_PHASES = ("NOT_STARTED", "DATA_COLLECTION", "STAKEHOLDER_CONSULTATION",
               "GAP_ANALYSIS", "CERTIFIED", "EXPIRED")
SEGMENTS = ("SECONDARY", "POSTSECONDARY")
COURSE_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
CREDENTIAL_TIERS = ("STATE_RECOGNIZED", "NATIONAL", "LOCAL")
SPECIAL_POPULATION_CODES = ("ECON_DISADV", "IEP", "EL", "SINGLE_PARENT", "NONTRADITIONAL")
CONCENTRATOR_STATUSES = ("PARTICIPANT", "CONCENTRATOR", "COMPLETER")
EXIT_REASONS = ("GRADUATED", "TRANSFERRED", "WITHDREW")
VERIFICATION_STATUSES = ("SELF_REPORTED", "VERIFIED")
COMMITTEE_STATUSES = ("FORMING", "ACTIVE", "DISSOLVED")
SECTORS = ("EMPLOYER", "POSTSECONDARY", "LABOR", "PARENT", "STUDENT")
MEMBER_STATUSES = ("ACTIVE", "EXPIRED")
AGENDA_KINDS = ("CLNA_STAKEHOLDER", "POS_ENDORSEMENT", "EQUIPMENT_REVIEW")
MINUTES_STATUSES = ("SCHEDULED", "FINALIZED", "AMENDED")
GRANT_STATUSES = ("OPEN", "CLOSED")
EXPENDITURE_CATEGORIES = ("EQUIPMENT", "CONSUMABLE", "PROFESSIONAL_DEVELOPMENT",
                          "ADMINISTRATION", "ENTERTAINMENT")
EXPENDITURE_STATUSES = ("REQUESTED", "CERTIFIED", "OBLIGATED", "DISALLOWED",
                        "VOIDED", "BLOCKED")
FINDING_CODES = ("ENTERTAINMENT_PROHIBITED", "ADMIN_CAP", "NO_CAPITAL_REVIEW",
                 "OUTSIDE_WINDOW", "OTHER")
DECISIONS = ("CERTIFY", "DISALLOW")
INDICATOR_CODES = ("1S1_GRAD_RATE", "2S1_ACADEMIC", "3S1_POST_PROGRAM",
                   "4S1_CREDENTIAL", "5S3_WORK_BASED")
INDICATOR_STATUSES = ("PROPOSED", "NEGOTIATING", "AGREED", "ARBITRATED", "MET",
                      "NOT_MET", "NOT_SCORED", "IMPROVEMENT_REQUIRED",
                      "MONITORING", "SANCTIONED")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED", "REJECTED_FINAL")
CERTIFICATION_ROUTES = ("TRADITIONAL", "INDUSTRY_EXPERIENCE", "ALTERNATIVE")
EDUCATOR_STATUSES = ("PROVISIONAL", "ELIGIBLE", "LAPSED")
ALIGNMENT_VARIANTS = ("PROVISIONAL_LOCAL", "FEDERAL_CERTIFIED")

ROUTE_HOUR_FLOOR = {"TRADITIONAL": 0, "ALTERNATIVE": 2000, "INDUSTRY_EXPERIENCE": 4000}

CLNA_SUCCESSOR = {
    "NOT_STARTED": "DATA_COLLECTION",
    "DATA_COLLECTION": "STAKEHOLDER_CONSULTATION",
    "STAKEHOLDER_CONSULTATION": "GAP_ANALYSIS",
    "GAP_ANALYSIS": "CERTIFIED",
    "CERTIFIED": "DATA_COLLECTION",
    "EXPIRED": "DATA_COLLECTION",
}


# ---------------------------------------------------------------- database
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.programs = {}
        self.courses = {}
        self.credentials = {}
        self.students = {}
        self.attainments = {}
        self.postings = {}
        self.committees = {}
        self.members = {}
        self.meetings = {}
        self.awards = {}
        self.expenditures = {}
        self.indicators = {}
        self.plans = {}
        self.educators = {}
        self.clock = _parse_instant(CLOCK_EPOCH)
        self._seq = itertools.count(1)


def next_seq():
    return next(db._seq)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------- time
def _parse_instant(text):
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    value = _dt.datetime.fromisoformat(raw)
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc)


def parse_instant(text):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return _parse_instant(text)
    except (ValueError, TypeError):
        return None


def parse_date(text):
    """Strict YYYY-MM-DD calendar date. Returns None when unparseable."""
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


db = DB()


def fmt_instant(value):
    return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (value.microsecond // 1000)


def fmt_date(value):
    return value.isoformat()


def now_wall():
    return _dt.datetime.now(_dt.timezone.utc)


def wall_stamp():
    return fmt_instant(now_wall())


def clock_instant():
    return db.clock


def clock_stamp():
    return fmt_instant(db.clock)


def clock_date():
    return db.clock.astimezone(_dt.timezone.utc).date()


def add_days(date_value, days):
    return date_value + _dt.timedelta(days=days)


# ---------------------------------------------------------------- numbers
def rhu(value, places):
    """round-half-up to `places` decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def num(value, places):
    """Serialise a Decimal/number as a JSON float at `places` decimal places."""
    if value is None:
        return None
    return float(rhu(dec(value), places))


# ---------------------------------------------------------------- records
def stamp_new(record, with_version=True):
    record["id"] = new_id()
    record["_seq"] = next_seq()
    now = wall_stamp()
    record["created_at"] = now
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = wall_stamp()
    record["version"] = int(record.get("version", 0)) + 1
    return record
