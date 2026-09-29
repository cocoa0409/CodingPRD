"""In-memory data store, logical clock and shared primitive helpers.

The store is empty on every boot.  Nothing is seeded, preloaded or hardcoded:
tests build every entity they need through the declared HTTP surface.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants

LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

CORRECTION_WINDOW_DAYS = 21
APPEAL_WINDOW_DAYS = 14
INVESTIGATION_DAYS = 30
METHODOLOGY_BUFFER_DAYS = 30
MAX_CORRECTION_ROUNDS = 2
TRANSITION_GRANT_DELTA = Decimal("-5.00")
MEDIA_NOTIFY_DELTA = Decimal("10.00")
COI_REVIEW_MAX_AGE_DAYS = 730
BOARD_SIZE_MIN = 5
BOARD_INDEPENDENCE_MIN = Decimal("0.5000")
BOARD_MEETINGS_MIN = 3
STANDARD_MET_POINTS = 3
STANDARD_WAIVED_POINTS = 2
OUTCOME_MEASURE_CAP = 4

DIMENSIONS = ["FINANCIAL_HEALTH", "ACCOUNTABILITY", "TRANSPARENCY", "IMPACT"]

ROLES = [
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "MethodologyAdmin",
    "OrganizationRep",
    "PublicUser",
]

ORG_TYPES = [
    "PUBLIC_CHARITY",
    "PRIVATE_FOUNDATION",
    "RELIGIOUS_CONGREGATION",
    "DONOR_ADVISED_SPONSOR",
    "MEMBERSHIP_ASSOCIATION",
]

SOURCE_KINDS = ["AUDITED_STATEMENT", "PUBLIC_FILING", "ORG_SUBMISSION"]
SOURCE_PRECEDENCE = {"AUDITED_STATEMENT": 1, "PUBLIC_FILING": 2, "ORG_SUBMISSION": 3}

STANDARD_CODES = [
    "BOARD_SIZE_MIN",
    "BOARD_INDEPENDENCE",
    "COI_POLICY",
    "COI_POLICY_CURRENCY",
    "BOARD_MEETING_FREQUENCY",
    "AUDIT_COMMITTEE",
    "WHISTLEBLOWER_POLICY",
    "CEO_COMP_REVIEW",
]

# ---------------------------------------------------------------- decimal

D0 = Decimal(0)
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")


def d(value):
    """Coerce to Decimal without ever passing through float()."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    return d(value).quantize(Q2, rounding=ROUND_HALF_UP)


def q4(value):
    return d(value).quantize(Q4, rounding=ROUND_HALF_UP)


def quant(value, places):
    return d(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- time

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_iso(text):
    """Parse an ISO-8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.match(text.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * offset).replace(tzinfo=timezone.utc)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def plus_days(moment, days):
    return moment + timedelta(days=days)


# ---------------------------------------------------------------- store


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = LOGICAL_CLOCK_DEFAULT
        self._counter = 0
        self.organizations = {}
        self.methodology_versions = {}
        self.public_comments = {}
        self.transition_grants = {}
        self.rating_cycles = {}
        self.filing_records = {}
        self.governance_profiles = {}
        self.standard_evaluations = {}
        self.dimension_scores = {}
        self.correction_requests = {}
        self.appeals = {}
        self.complaints = {}
        self.publication_records = {}

    # -- identity / clock ------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._counter += 1
        return self._counter

    def now(self):
        return self.clock


store = Store()

COLLECTION_FOR_ENTITY = {
    "Organization": "organizations",
    "MethodologyVersion": "methodology_versions",
    "PublicComment": "public_comments",
    "TransitionGrant": "transition_grants",
    "RatingCycle": "rating_cycles",
    "FilingRecord": "filing_records",
    "GovernanceProfile": "governance_profiles",
    "StandardEvaluation": "standard_evaluations",
    "DimensionScore": "dimension_scores",
    "CorrectionRequest": "correction_requests",
    "Appeal": "appeals",
    "Complaint": "complaints",
    "PublicationRecord": "publication_records",
}


def collection(entity):
    return getattr(store, COLLECTION_FOR_ENTITY[entity])


def lookup(entity, ident):
    if not isinstance(ident, str) or not ident:
        return None
    return collection(entity).get(ident)


def rows(entity):
    """All rows of an entity in insertion order."""
    return list(collection(entity).values())


def new_row(entity, fields, versioned=True):
    """Create a row with the system fields the PRD declares."""
    record = {"id": store.new_id()}
    record.update(fields)
    record["created_at"] = store.now()
    if versioned:
        record["updated_at"] = store.now()
        record["version"] = 1
    record["_seq"] = store.next_seq()
    collection(entity)[record["id"]] = record
    return record


def touch(record):
    """One mutation: refresh updated_at and advance the row's own version."""
    record["updated_at"] = store.now()
    record["version"] = int(record.get("version") or 0) + 1
    return record
