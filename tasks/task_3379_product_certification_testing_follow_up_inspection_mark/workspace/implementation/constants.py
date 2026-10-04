"""All named constants for the certification domain. Every literal referenced
elsewhere in the codebase is defined here exactly once."""
from decimal import Decimal

# ---- Roles (PRD 2.1) ----
ROLE_ADMIN = "CertificationBodyAdmin"
ROLE_REP = "ManufacturerRep"
ROLE_ENGINEER = "TestEngineer"
ROLE_REVIEWER = "CertificationReviewer"
ROLE_INSPECTOR = "FactoryInspector"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_AHJ = "AHJAuthority"
ALL_ROLES = (
    ROLE_ADMIN, ROLE_REP, ROLE_ENGINEER, ROLE_REVIEWER,
    ROLE_INSPECTOR, ROLE_COMPLIANCE, ROLE_AHJ,
)
ENTITY_BACKED_ROLES = {ROLE_REP: "manufacturers", ROLE_AHJ: "jurisdictions"}

# ---- Logical clock ----
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# ---- test_outcome_determination ----
CONDITIONAL_BAND_PCT = Decimal("0.95")

# ---- project_fee_calculation ----
DAMAGED_FEE_MULTIPLIER = Decimal("1.25")
SMALL_CLIENT_DISCOUNT = Decimal("0.10")
RETEST_SURCHARGE_PCT = Decimal("0.5")

# ---- factory_conformity_score ----
PENALTY_CRITICAL = 40
PENALTY_MAJOR = 15
PENALTY_MINOR = 5
PENALTY_BY_SEVERITY = {
    "CRITICAL": PENALTY_CRITICAL,
    "MAJOR": PENALTY_MAJOR,
    "MINOR": PENALTY_MINOR,
}
PROBATION_THRESHOLD = Decimal("70")
SCORE_MID_THRESHOLD = Decimal("90")
WINDOW_MONTHS = 24

# ---- label_quota_allocation ----
STANDARD_HARD_CAP = 100000
PROBATION_HARD_CAP = 500
MIN_LOT = 100
STANDARD_QUOTA_MULT = Decimal("1.10")
PROBATION_QUOTA_MULT = Decimal("0.25")

# ---- inspection_interval_derived ----
INTERVAL_HIGH_MONTHS = 12
INTERVAL_MID_MONTHS = 6
INTERVAL_PROBATION_MONTHS = 3

# ---- inspection_scheduling_gap ----
MIN_INSPECTION_GAP_DAYS = 25

# ---- withdrawal notices ----
NOTICE_PERIOD_DAYS = 14

# ---- pagination (response_envelope.pagination_defaults) ----
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# ---- enums ----
REVENUE_TIERS = ("MICRO", "SMALL", "STANDARD", "ENTERPRISE")
RECIPROCITY_GROUPS = ("NONE", "NATIONAL", "BILATERAL_EU", "CUSTOMS_UNION")
SAMPLE_CONDITIONS = ("INTACT", "DAMAGED")
PROJECT_DECISION_OUTCOMES = ("APPROVED", "REJECTED", "RETEST")
TRIAGE_DECISIONS = ("ACCEPT", "REJECT")
SUBSTITUTION_OUTCOMES = ("APPROVE", "REJECT")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
LABEL_TYPES = ("STANDARD", "HOLOGRAM", "SECURED")
EVAL_OUTCOMES = ("PASS", "FAIL")
ACCEPTANCE_DECISIONS = ("ACCEPT", "REJECT")
WITHDRAWAL_REASON_CODES = ("SAFETY", "NONCONFORMITY", "VOLUNTARY", "MISUSE_OF_MARK")
