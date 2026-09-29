"""Domain constants for the crime-laboratory case-management API.

Every literal here is transcribed from the PRD: the logical-clock origin, the
numeric thresholds named in the business rules, the enumerations declared on the
entities, and the endpoint path prefix.
"""

# ─── Routing ──────────────────────────────────────────

API_PREFIX = "/lab"

# ─── Logical clock (PRD §2.5) ─────────────────────────

# "the clock starts at exactly 2026-08-01T00:00:00Z"
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ─── Method validation (PRD §3.2) ─────────────────────

MIN_VALIDATION_STUDY_ITEMS = 12
MAX_VALIDATION_CV_PCT = 5.00

# ─── Analyst workload / assignment (PRD §3.4) ─────────

MAX_PROJECTED_UTILIZATION_PCT = 100.00

# ─── Proficiency testing (PRD §3.8) ───────────────────

PT_PASS_FLOOR_PCT = 90.00
PT_INCONCLUSIVE_FLOOR_PCT = 70.00
PT_SUSPENSION_THRESHOLD = 2

# ─── Corrective action (PRD §3.8) ─────────────────────

CAPA_SLA_DAYS = {"MINOR": 60, "MAJOR": 30, "CRITICAL": 10}
CAPA_ESCALATION_THRESHOLD = 2
SEVERITY_LADDER = ["MINOR", "MAJOR", "CRITICAL"]

# ─── Discovery (PRD §3.9) ─────────────────────────────

DISCOVERY_RESPONSE_DAYS = 30

# ─── Testimony calendar (PRD §3.9) ────────────────────

TRAVEL_BUFFER_MINUTES = 60
MIN_TESTIMONY_NOTICE_DAYS = 7

# ─── Vendor ledger (PRD §3.7) ─────────────────────────

VENDOR_VARIANCE_TOLERANCE_PCT = 10
VOLUME_TIERS = [(500000, 0.12), (250000, 0.08), (100000, 0.04)]

# ─── Backlog reporting (PRD §3.9) ─────────────────────

OUTSOURCING_INDEX_THRESHOLD = 45.00
PRIORITY_CLASS_WEIGHTS = {"P1_STATUTORY": 1.50, "P2_VIOLENT": 1.25, "P3_ROUTINE": 1.00}

# ─── Pagination (PRD §2.3) ────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Enumerations (PRD §3, entity field declarations) ──

DISCIPLINES = ["BIOLOGY", "CHEMISTRY", "LATENT_PRINTS", "TRACE", "DIGITAL"]

ITEM_TYPES = [
    "BIOLOGICAL",
    "CHEMICAL",
    "FIREARM",
    "LATENT_LIFT",
    "DIGITAL_DEVICE",
    "TRACE_MEDIA",
]

# PRD §3.3 discipline-to-item-type pairings.
DISCIPLINE_ITEM_TYPES = {
    "BIOLOGY": ["BIOLOGICAL"],
    "CHEMISTRY": ["CHEMICAL"],
    "LATENT_PRINTS": ["LATENT_LIFT", "FIREARM"],
    "TRACE": ["TRACE_MEDIA"],
    "DIGITAL": ["DIGITAL_DEVICE"],
}

OFFENSE_CATEGORIES = [
    "HOMICIDE",
    "SEXUAL_ASSAULT",
    "AGG_ASSAULT",
    "ROBBERY",
    "BURGLARY",
    "DRUG_OFFENSE",
    "PROPERTY_CRIME",
    "OTHER",
]

# PRD §3.1: the four offence categories that carry the violence multiplier.
VIOLENT_OFFENSE_CATEGORIES = ["HOMICIDE", "SEXUAL_ASSAULT", "AGG_ASSAULT", "ROBBERY"]

PRIORITY_CLASSES = ["P1_STATUTORY", "P2_VIOLENT", "P3_ROUTINE"]

CASE_WORKFLOW_STATUSES = [
    "SUBMITTED",
    "ACCEPTED",
    "IN_PROGRESS",
    "AWAITING_ASSIGNMENT",
    "REPORTED",
    "REJECTED",
]

DISCOVERY_STATUSES = ["NONE", "RECEIVED", "FULFILLED", "DENIED"]

CUSTODY_STATUSES = ["IN_VAULT", "IN_ANALYSIS", "RETURNED", "CONSUMED"]

EXAM_REQUEST_STATUSES = [
    "QUEUED",
    "ASSIGNED",
    "IN_ANALYSIS",
    "TECH_REVIEW",
    "DISAGREEMENT",
    "ADMIN_REVIEW",
    "OUTSOURCED",
    "RELEASED",
    "CANCELLED",
]

# PRD §2.10 rollup partitions.
ACTIVE_REQUEST_STATUSES = [
    "ASSIGNED",
    "IN_ANALYSIS",
    "TECH_REVIEW",
    "DISAGREEMENT",
    "ADMIN_REVIEW",
    "OUTSOURCED",
]
TERMINAL_REQUEST_STATUSES = ["RELEASED", "CANCELLED"]
HOLD_REQUEST_STATUSES = ["ASSIGNED", "IN_ANALYSIS"]

ASSIGNMENT_STATUSES = ["ACTIVE", "SUPERSEDED", "RELEASED", "COMPLETED"]
ASSIGNMENT_REASONS = ["MANUAL", "AUTO_BALANCED"]

REVIEW_TYPES = ["TECHNICAL", "ADMINISTRATIVE", "DISAGREEMENT_RESOLUTION"]

ANALYST_EMPLOYMENT_STATUSES = ["ACTIVE", "ON_LEAVE", "SEPARATED"]
QUALIFICATION_STATES = ["QUALIFIED", "PROBATION", "SUSPENDED", "DECERTIFIED"]

METHOD_VALIDATION_STATUSES = ["DRAFT", "VALIDATED", "RETIRED"]

PT_STATUSES = ["ASSIGNED", "SUBMITTED", "SCORED"]
PT_RESULTS = ["PASS", "INCONCLUSIVE", "FAIL"]

VENDOR_STATUSES = ["ACTIVE", "SUSPENDED"]
VENDOR_ENGAGEMENT_STATUSES = ["AWARDED", "AT_VENDOR", "RETURNED", "CANCELLED"]

NONCONFORMANCE_SOURCES = [
    "TECHNICAL_DISAGREEMENT",
    "PT_FAILURE",
    "PT_INCONCLUSIVE",
    "ACCREDITATION_AUDIT",
    "INTERNAL_QA",
    "DEADLINE_MISS",
    "VENDOR_VARIANCE",
]
NONCONFORMANCE_STATUSES = [
    "OPEN",
    "ROOT_CAUSE_SUBMITTED",
    "CAPA_APPROVED",
    "CLOSED",
    "VOIDED",
]
# PRD §3.8: the finding states that still count as attributed and open.
UNRESOLVED_NONCONFORMANCE_STATUSES = ["OPEN", "ROOT_CAUSE_SUBMITTED", "CAPA_APPROVED"]

ROOT_CAUSE_CATEGORIES = [
    "TRAINING",
    "METHOD_DEFICIENCY",
    "EQUIPMENT",
    "DOCUMENTATION",
    "WORKLOAD",
    "VENDOR",
]

COURT_EVENT_STATUSES = ["SCHEDULED", "CONFIRMED", "TESTIFIED", "CANCELLED"]

# ─── Common-field carriers (PRD §2.4) ─────────────────

# Entities that carry updated_at and version in addition to id and created_at.
VERSIONED_ENTITIES = [
    "Analyst",
    "Method",
    "Case",
    "EvidenceItem",
    "ExaminationRequest",
    "Assignment",
    "ProficiencyTest",
    "Vendor",
    "VendorEngagement",
    "Nonconformance",
    "CourtEvent",
]
# ReviewRecord is immutable and carries only id and created_at.
IMMUTABLE_ENTITIES = ["ReviewRecord"]
