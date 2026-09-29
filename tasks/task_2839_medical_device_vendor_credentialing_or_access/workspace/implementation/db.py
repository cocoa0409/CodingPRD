"""In-memory data store.

Storage is plain Python dicts keyed by id.  The store starts completely empty
on every boot: nothing is seeded, preloaded, registered or hardcoded.  Every
entity the API exposes is created by a caller through a declared endpoint.
"""
import itertools
import uuid

from timeutil import fmt_instant, parse_instant

# --------------------------------------------------------------------------
# Global constants (PRD sections 2.4, 3.1-3.9)
# --------------------------------------------------------------------------
LOGICAL_CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

ROLES = (
    "VendorAdmin",
    "VendorRepUser",
    "CredentialingOfficer",
    "ORCoordinator",
    "ClinicalSponsor",
    "ValueAnalysisApprover",
    "SterileProcessingTech",
    "ComplianceAdmin",
)
ALL_ROLES = list(ROLES)

CREDENTIAL_TYPES = (
    "IMMUNIZATION_INFLUENZA",
    "IMMUNIZATION_MMR",
    "TRAINING_BLOODBORNE_PATHOGENS",
    "TRAINING_OR_PROTOCOL",
    "BACKGROUND_CHECK",
    "COI_GIFT_ATTESTATION",
)
GATING_CREDENTIAL_TYPES = (
    "IMMUNIZATION_INFLUENZA",
    "TRAINING_BLOODBORNE_PATHOGENS",
    "BACKGROUND_CHECK",
    "COI_GIFT_ATTESTATION",
)
CREDENTIAL_STATUSES = (
    "PENDING_VERIFICATION",
    "VERIFIED",
    "EXPIRING_SOON",
    "EXPIRED",
    "REJECTED",
)

REP_ACCESS_STATUSES = ("PENDING_CREDENTIALING", "CREDENTIALED", "SUSPENDED", "REVOKED")
REP_POSTURES = ("INCOMPLETE", "COMPLIANT", "EXPIRING_SOON", "LAPSED")
SUSPENSION_REASONS = ("NONE", "CREDENTIAL_LAPSED", "INCIDENT_SUBSTANTIATED")

CASE_STATUSES = ("SCHEDULED", "RESCHEDULED", "CANCELLED")
RESTRICTION_LEVELS = ("STANDARD", "RESTRICTED")
COVERAGE_STATUSES = ("NOT_REQUIRED", "COVERED", "AT_RISK", "UNCOVERED")
READINESS_STATUSES = ("NOT_APPLICABLE", "PENDING", "READY", "BLOCKED")

AUTH_STATUSES = ("REQUESTED", "APPROVED", "DENIED", "REVOKED")
REQUESTED_ROLES = ("IMPLANT_SUPPORT", "TECHNICAL_SUPPORT", "OBSERVATION")
REVOKED_REASONS = (
    "NONE",
    "REP_SUSPENDED",
    "REP_REVOKED",
    "CASE_CANCELLED",
    "COORDINATOR_WITHDRAWN",
    "MANUAL",
)

PIR_STATUSES = (
    "DRAFT",
    "CLINICAL_REVIEW",
    "VALUE_ANALYSIS_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "REJECTED",
)
PIR_OPEN_STATUSES = ("DRAFT", "CLINICAL_REVIEW", "VALUE_ANALYSIS_REVIEW", "CHANGES_REQUESTED")
MAX_REVISION_ROUNDS = 2

PRODUCT_STATUSES = ("ACTIVE", "SUSPENDED", "EXPIRED")
PRODUCT_SUSPENDED_REASONS = ("NONE", "INCIDENT_SUBSTANTIATED", "APPROVAL_EXPIRED", "SUPERSEDED")
APPROVAL_VALIDITY_DAYS = 365

LOANER_STATUSES = (
    "EXPECTED",
    "DELIVERED_ON_TIME",
    "DELIVERED_LATE",
    "REJECTED_LATE",
    "HELD",
    "RELEASED_TO_OR",
)
LOANER_BAY_OCCUPYING_STATUSES = ("EXPECTED", "DELIVERED_ON_TIME", "DELIVERED_LATE", "HELD")
FEE_STATUSES = ("NONE", "WAIVED", "ASSESSED", "REVERSED")
COMPLEXITIES = ("SIMPLE", "COMPLEX", "IMPLANT_SPECIALTY")
COMPLEXITY_HOURS = {"SIMPLE": 2, "COMPLEX": 6, "IMPLANT_SPECIALTY": 10}
COMPLEXITY_FEE_MULTIPLIER = {"SIMPLE": "1.0", "COMPLEX": "1.35", "IMPLANT_SPECIALTY": "1.75"}
IMPLANT_MIN_LEAD_HOURS = 24
HARD_REJECT_GRACE_MINUTES = 120
PER_TRAY_BASE_RATE_CENTS_PER_MINUTE = "2.5"
LATE_FEE_CAP_CENTS = 250000
FEE_HOLD_THRESHOLD_CENTS = 100000
SPD_BAY_BUFFER_MINUTES = 30

BADGE_STATUSES = ("ISSUED", "CHECKED_OUT", "EXPIRED", "VOIDED")
ESCORT_STATUSES = (
    "ESCORT_NOT_REQUIRED",
    "ESCORT_PENDING",
    "ESCORT_ATTACHED",
    "ESCORT_RELEASED",
)

INCIDENT_TYPES = (
    "UNAPPROVED_PRODUCT_USE",
    "UNBADGED_ACCESS",
    "LOANER_LATE_DELIVERY",
    "GIFT_POLICY_VIOLATION",
)
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
INCIDENT_STATUSES = (
    "REPORTED",
    "UNDER_INVESTIGATION",
    "SUBSTANTIATED",
    "UNSUBSTANTIATED",
    "CLOSED",
)
INCIDENT_OPEN_STATUSES = ("REPORTED", "UNDER_INVESTIGATION")
ADJUDICATED_OUTCOMES = ("NONE", "SUBSTANTIATED", "UNSUBSTANTIATED")
SEVERITY_WEIGHT = {"MINOR": 3, "MAJOR": 8, "CRITICAL": 20}
INCIDENT_CLOSE_DAYS = 30

APPEAL_STATUSES = ("SUBMITTED", "UPHELD", "OVERTURNED")
APPEAL_WINDOW_DAYS = 14

BASE_SCORE = 100
SCORE_FLOOR = 0
SCORE_CEILING = 100
W_LATE_DELIVERY = 5
W_LAPSED_REP = 6
W_UTILIZATION_OVERAGE = 12
BASE_QUOTA = 4
QUOTA_HARD_MULTIPLIER = "1.5"
TIER_STEP = {"TIER_PLATINUM": "1.5", "TIER_STANDARD": "1.0", "TIER_PROBATION": "0.4"}
TIER_PLATINUM_MIN_SCORE = 90
TIER_STANDARD_MIN_SCORE = 70
SCORECARD_TIERS = ("TIER_PLATINUM", "TIER_STANDARD", "TIER_PROBATION")
COMPLIANCE_STATUSES = ("IN_GOOD_STANDING", "WATCH", "PROBATION", "BARRED")
EXPIRY_WARNING_DAYS = 14


class Store(object):
    """Every collection is a plain dict keyed by row id."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.facilities = {}
        self.vendors = {}
        self.vendor_reps = {}
        self.credentials = {}
        self.surgical_cases = {}
        self.authorizations = {}
        self.pirs = {}
        self.approved_products = {}
        self.loaner_sets = {}
        self.check_ins = {}
        self.incidents = {}
        self.appeals = {}
        self.sweeps = {}
        self.badge_counters = {}
        self._seq = itertools.count(1)
        self.clock = parse_instant(LOGICAL_CLOCK_DEFAULT_UTC)


store = Store()


def now():
    """The logical current UTC instant (PRD 2.4)."""
    return store.clock


def now_str():
    return fmt_instant(store.clock)


def next_seq():
    return next(store._seq)


def new_id():
    return str(uuid.uuid4())


def stamp_common(row):
    """Attach the four system-managed common properties (PRD 2.5)."""
    moment = now_str()
    row["id"] = new_id()
    row["created_at"] = moment
    row["updated_at"] = moment
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version (PRD 2.5 / 2.8)."""
    row["updated_at"] = now_str()
    row["version"] = row.get("version", 0) + 1
    return row


def public(row):
    """Strip internal bookkeeping keys before serialisation."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def in_creation_order(rows):
    """PRD 2.8: sibling fan-out is processed in ascending creation timestamp."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
