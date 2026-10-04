"""Pinned constants for task_3378 (Business Accreditation, Complaint Mediation
& Rating Methodology). Every value traces to a literal in PRD.md / SCAFFOLD.yaml.
"""
from decimal import Decimal

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4): startup default, never wall-clock.
# ---------------------------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles and auth headers (PRD section 2.1)
# ---------------------------------------------------------------------------
ROLE_BUREAU_ADMIN = "BureauAdmin"
ROLE_STANDARDS_REVIEWER = "StandardsReviewer"
ROLE_BUSINESS_REP = "BusinessRep"
ROLE_CONSUMER = "Consumer"
ALL_ROLES = frozenset({
    ROLE_BUREAU_ADMIN,
    ROLE_STANDARDS_REVIEWER,
    ROLE_BUSINESS_REP,
    ROLE_CONSUMER,
})
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ---------------------------------------------------------------------------
# Size tiers (PRD section 3.1 / scaffold territory_assignment)
# ---------------------------------------------------------------------------
TIER_MICRO = "MICRO"
TIER_SMALL = "SMALL"
TIER_MEDIUM = "MEDIUM"
TIER_LARGE = "LARGE"
TIER_MICRO_MAX_EMPLOYEES = 4
TIER_SMALL_MAX_EMPLOYEES = 19
TIER_MEDIUM_MAX_EMPLOYEES = 99

# ---------------------------------------------------------------------------
# Accreditation dues (PRD section 3.3 / scaffold dues_amount)
# ---------------------------------------------------------------------------
DUES_BASE_CENTS = {
    TIER_MICRO: 42500,
    TIER_SMALL: 68000,
    TIER_MEDIUM: 115000,
    TIER_LARGE: 240000,
}
ANNUAL_PREPAID_MULTIPLIER = Decimal("0.95")      # 5% prepay discount
QUARTERLY_SURCHARGE_MULTIPLIER = Decimal("1.04")  # 4% plan surcharge
QUARTERLY_INSTALLMENT_COUNT = 4
INVOICE_DUE_DAYS = 30
INVOICE_VOID_GRACE_DAYS = 15
VOID_RECENCY_DAYS = 365
BILLING_PLANS = frozenset({"ANNUAL_PREPAID", "QUARTERLY"})
CHECKLIST_RESULTS = frozenset({"PASS", "FAIL"})
DECISIONS = frozenset({"APPROVE", "DENY"})

# ---------------------------------------------------------------------------
# Accreditation eligibility (PRD section 3.2 / business_age_years)
# ---------------------------------------------------------------------------
ACCREDITATION_MIN_AGE_DAYS = 183
REAPPLICATION_COOLING_DAYS = 30

# ---------------------------------------------------------------------------
# Complaints (PRD section 3.4)
# ---------------------------------------------------------------------------
RESPONSE_WINDOW_SECONDS = 1209600  # exactly 14 days
REBUTTAL_CAP = 3
REOPEN_WINDOW_DAYS = 30
MEDIATION_OFFER_WINDOW_DAYS = 14
MEDIATION_OFFER_DEADLINE_DAYS = 7
COMPLAINT_CATEGORIES = frozenset({
    "SERVICE", "PRODUCT", "BILLING", "ADVERTISING", "DELIVERY", "WARRANTY", "OTHER",
})
RESPONSE_KINDS = frozenset({
    "BUSINESS_RESPONSE", "CONSUMER_REBUTTAL", "CONSUMER_ACCEPT", "CONSUMER_REJECT",
})

# Rating input partitions (PRD section 3.6)
COMPLAINT_OUTCOME_STATES = frozenset({
    "RESOLVED", "UNANSWERED", "UNRESOLVED",
    "MEDIATION_RESOLVED", "MEDIATION_FAILED", "ARBITRATED",
})
COMPLAINT_PENDING_STATES = frozenset({
    "RECEIVED", "FORWARDED", "RESPONSE_RECEIVED", "CONSUMER_REBUTTED",
    "MEDIATION_OFFERED", "IN_MEDIATION", "IN_ARBITRATION",
})
# Business counter definitions (PRD section 3.4 tail)
COMPLAINT_OPEN_STATES = frozenset({
    "RECEIVED", "FORWARDED", "RESPONSE_RECEIVED", "CONSUMER_REBUTTED",
    "MEDIATION_OFFERED", "IN_MEDIATION", "UNRESOLVED", "MEDIATION_FAILED",
    "IN_ARBITRATION",
})
COMPLAINT_CLOSED_STATES = frozenset({
    "RESOLVED", "UNANSWERED", "MEDIATION_RESOLVED", "ARBITRATED",
})
COMPLAINT_UNRESOLVED_STATES = frozenset({"UNRESOLVED", "MEDIATION_FAILED"})

# ---------------------------------------------------------------------------
# Mediation / arbitration (PRD section 3.5)
# ---------------------------------------------------------------------------
HEARING_ROOM_BUFFER_MINUTES = 30
MEDIATION_PARTIES = frozenset({"BUSINESS", "CONSUMER"})
MEDIATION_PARTY_RESPONSES = frozenset({"ACCEPTED", "DECLINED"})
MEDIATION_OUTCOMES = frozenset({"AGREEMENT", "NO_AGREEMENT"})
ARBITRATION_OUTCOMES = frozenset({"ADVERSE_TO_BUSINESS", "NO_FAULT"})

# ---------------------------------------------------------------------------
# Rating methodology (PRD section 3.6 / scaffold rating_score)
# ---------------------------------------------------------------------------
RATING_WINDOW_DAYS = 1095
VOLUME_THRESHOLDS = {
    TIER_MICRO: 3,
    TIER_SMALL: 6,
    TIER_MEDIUM: 12,
    TIER_LARGE: 24,
}
VOLUME_POINTS_PER_EXCESS = 6
VOLUME_CAP = 30
UNANSWERED_POINTS_EACH = 12
UNANSWERED_CAP = 36
UNRESOLVED_POINTS_EACH = 8
UNRESOLVED_CAP = 24
ARBITRATION_ADVERSE_POINTS_EACH = 10
ARBITRATION_CAP = 20
AGE_FREE_YEARS = 3
AGE_POINTS_PER_YEAR_UNDER_FREE = 2
AGE_CAP = 6
ADVERTISING_REFERRED_POINTS = 15
ADVERTISING_UNDER_REVIEW_POINTS = 5
SCAM_PATTERN_MIN_REPORTS = 3
SCAM_PATTERN_WINDOW_DAYS = 365
SCAM_PATTERN_POINTS = 10
PENDING_POINTS_EACH = 4
PENDING_CAP = 12
SNAPSHOT_VARIANTS = frozenset({"PROVISIONAL", "PUBLISHED"})
# Inclusive lower-bound grade floors (PRD section 3.6)
GRADE_FLOORS = [
    (97, "A_PLUS"),
    (94, "A"),
    (90, "A_MINUS"),
    (85, "B_PLUS"),
    (80, "B"),
    (75, "B_MINUS"),
    (70, "C_PLUS"),
    (65, "C"),
    (60, "C_MINUS"),
    (55, "D_PLUS"),
    (50, "D"),
]
GRADE_F = "F"

# ---------------------------------------------------------------------------
# Suspension scan (PRD section 3.7 / scaffold suspension_scan)
# ---------------------------------------------------------------------------
SUSPEND_SCORE_THRESHOLD = 75
REINSTATE_SCORE_THRESHOLD = 80
REVOKE_SUSPENSION_COUNT = 2
SUSPENSION_WINDOW_DAYS = 730

# Rating disputes (PRD section 3.7)
DISPUTE_WINDOW_DAYS = 10
DISPUTE_DECISIONS = frozenset({"UPHELD", "OVERRULED"})

# ---------------------------------------------------------------------------
# Advertising reviews (PRD section 3.8)
# ---------------------------------------------------------------------------
AD_REVIEW_OUTCOMES = frozenset({"CLEARED", "SUBSTANTIATED_DECEPTIVE"})

# ---------------------------------------------------------------------------
# Ledger entries (PRD section 3.3)
# ---------------------------------------------------------------------------
LEDGER_KINDS = frozenset({"PAYMENT", "REFUND"})

# ---------------------------------------------------------------------------
# Pagination (scaffold section 1.0 response_envelope)
# ---------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
