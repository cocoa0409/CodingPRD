"""Domain constants for the Robocall Mitigation & Call Authentication API.

Every value here is transcribed from the requirements document: endpoint paths,
enumeration members, thresholds, weights and the logical-clock default.
"""

# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------
CLOCK_PATH = "/_clock/set_current_utc"
BASE = "/rmd"

SWEEPS = f"{BASE}/compliance-sweeps"
PROVIDERS = f"{BASE}/providers"
CERTIFICATES = f"{BASE}/certificates"
MITIGATION_PLANS = f"{BASE}/mitigation-plans"
CUSTOMERS = f"{BASE}/customers"
NUMBER_ASSIGNMENTS = f"{BASE}/number-assignments"
CALL_ATTESTATIONS = f"{BASE}/call-attestations"
TRAFFIC_OBSERVATIONS = f"{BASE}/traffic-observations"
TRACEBACK_REQUESTS = f"{BASE}/traceback-requests"
ILLEGAL_TRAFFIC_NOTICES = f"{BASE}/illegal-traffic-notices"
BLOCKING_EVENTS = f"{BASE}/blocking-events"
BLOCKING_DISPUTES = f"{BASE}/blocking-disputes"
ENFORCEMENT_ACTIONS = f"{BASE}/enforcement-actions"
EFFECTIVENESS_REPORTS = f"{BASE}/effectiveness-reports"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# "On startup the clock is set to exactly 2026-08-01T00:00:00Z."
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_REGULATOR = "Regulator"
ROLE_POLICY_ADMINISTRATOR = "PolicyAdministrator"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_KYC_ANALYST = "KycAnalyst"
ROLE_FRAUD_ANALYST = "FraudAnalyst"
ROLE_PROVIDER_ADMIN = "ProviderAdmin"
ROLE_CALLER = "Caller"

ALL_ROLES = (
    ROLE_REGULATOR,
    ROLE_POLICY_ADMINISTRATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_KYC_ANALYST,
    ROLE_FRAUD_ANALYST,
    ROLE_PROVIDER_ADMIN,
    ROLE_CALLER,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
PROVIDER_TYPES = ("FACILITIES_BASED", "NON_FACILITIES_RESELLER", "GATEWAY")

RMD_FILING_STATUSES = ("UNFILED", "PARTIAL", "COMPLETE")

AUTH_POSTURES = ("SIGNING_SUSPENDED", "GATEWAY_LIMITED", "FULL_ATTESTATION")

PREVENTION_PRACTICES = (
    "KYC_ONBOARDING",
    "TRAFFIC_PATTERN_MONITORING",
    "CONTRACT_TERMS_PROHIBITION",
    "CALL_BLOCKING_ANALYTICS",
    "TRACEBACK_COOPERATION",
)
# The minimum compliant practice set: three practices that include both
# mandatory members.
MINIMUM_COMPLIANT_PRACTICES = (
    "KYC_ONBOARDING",
    "TRACEBACK_COOPERATION",
    "TRAFFIC_PATTERN_MONITORING",
)

PLAN_FILING_STATES = (
    "DRAFT",
    "SUBMITTED",
    "ACCEPTED",
    "DEFICIENT",
    "WITHDRAWN",
    "SUPERSEDED",
)

CERTIFICATE_STATUSES = (
    "REQUESTED",
    "ISSUED",
    "ACTIVE",
    "SUPERSEDED",
    "REVOKED",
    "EXPIRED",
)
REVOCATION_REASONS = ("KEY_COMPROMISE", "SPC_WITHDRAWN", "REGULATOR_ORDER")

KYC_EVIDENCE_LEVELS = (
    "BUSINESS_REGISTRY_VERIFIED",
    "CONTRACT_ONLY",
    "SELF_ATTESTED",
)
KYC_STATES = ("PENDING", "UNDER_REVIEW", "VERIFIED", "REJECTED")
KYC_DECISIONS = ("VERIFY", "REJECT")

ORIGINATION_STATES = ("DISABLED", "ENABLED", "SUSPENDED", "TERMINATED")
ORIGINATION_ACTIONS = ("ENABLE", "SUSPEND", "RESTORE", "TERMINATE")
SUSPENSION_CAUSES = (
    "PROVIDER_REQUEST",
    "REGULATOR_ORDER",
    "NOTICE_EXPIRY",
    "TRAFFIC_RISK_THRESHOLD",
    "BLOCKING_ANALYTICS",
)

ASSIGNMENT_STATUSES = ("ACTIVE", "SUSPENDED_BY_CUSTOMER", "REVOKED")
OWNERSHIP_EVIDENCE = (
    "DIRECT_ALLOCATION",
    "PORTED_IN",
    "LEASED_FROM_CARRIER",
    "UNVERIFIED",
)
# Only these two count as verified ownership.
VERIFIED_OWNERSHIP_EVIDENCE = ("DIRECT_ALLOCATION", "PORTED_IN")

ATTESTATION_LEVELS = ("A", "B", "C")
ATTESTATION_REASON_CODES = (
    "FULL_KYC_AND_OWNERSHIP",
    "KYC_ONLY_NO_OWNERSHIP",
    "OWNERSHIP_WITH_PARTIAL_KYC",
    "NO_VERIFIED_BASIS",
    "GATEWAY_PASSTHROUGH",
    "RISK_DOWNGRADE",
    "POSTURE_DOWNGRADE",
)

RISK_TIERS = ("LOW", "ELEVATED", "HIGH")

TRACEBACK_STATES = ("RECEIVED", "RESPONDED", "RESPONDED_LATE", "OVERDUE")

NOTICE_STATES = (
    "NOTIFIED",
    "UNDER_INVESTIGATION",
    "MITIGATED",
    "ALL_TRAFFIC_BLOCKED",
    "EXPIRED_UNMITIGATED",
)
MITIGATION_ACTIONS = ("CUSTOMER_TERMINATED", "NUMBERS_REVOKED", "TRAFFIC_BLOCKED")

BLOCKING_REASONS = ("ANALYTICS_SCORE", "NOTICE_MANDATE", "UNSIGNED_TRAFFIC")
BLOCKING_EVENT_STATUSES = ("BLOCKED", "REVERSED")

DISPUTE_STATES = ("FILED", "UNDER_REVIEW", "UPHELD", "REVERSED", "WITHDRAWN")
DISPUTE_OUTCOMES = ("UPHOLD", "REVERSE")

ENFORCEMENT_BASES = (
    "LATE_TRACEBACK",
    "UNMITIGATED_NOTICE",
    "FALSE_ATTESTATION",
    "UNFILED_PLAN",
)
ASSESSMENT_BASES = ("PER_VIOLATION", "CONTINUING_DAILY")
ENFORCEMENT_STATUSES = (
    "PROPOSED",
    "CONTESTED",
    "SUSTAINED",
    "DISMISSED",
    "PAID",
)
ADJUDICATION_OUTCOMES = ("SUSTAIN", "DISMISS")
FORFEITURE_TIERS = ("TIER_1", "TIER_2", "TIER_3")

REPORT_VARIANTS = ("PROVISIONAL", "CERTIFIED")
REPORT_STATES = ("GENERATED", "SIGNED_OFF", "FILED", "SUPERSEDED")
EFFECTIVENESS_BANDS = ("HIGH", "MID", "LOW", "NONE")
ATTESTATION_SUFFICIENCY = ("SUFFICIENT", "INSUFFICIENT")

# ---------------------------------------------------------------------------
# Thresholds and weights
# ---------------------------------------------------------------------------
PENALTY_POINT_SUSPENSION_THRESHOLD = 10
POINTS_PER_DEFICIENCY = 2
POINTS_PER_LATE_TRACEBACK = 3
POINTS_PER_EXPIRED_UNMITIGATED_NOTICE = 5

RISK_TIER_HIGH_MIN = 0.7500
RISK_TIER_ELEVATED_MIN = 0.4000
RISK_AUTO_SUSPEND_MIN = 0.9000

BLOCKING_SCORE_MIN = 0.6500
BLOCKING_AUTO_SUSPEND_MIN = 0.9500

RECENCY_WEIGHTS = (0.50, 0.30, 0.20)
SUBSCORE_SHORT_WEIGHT = 0.45
SUBSCORE_UNANSWERED_WEIGHT = 0.35
SUBSCORE_COMPLAINT_WEIGHT = 0.20
SUBSCORE_COMPLAINT_MULTIPLIER = 50

EFFECTIVENESS_ATTESTATION_WEIGHT = 0.40
EFFECTIVENESS_TRACEBACK_WEIGHT = 0.35
EFFECTIVENESS_NOTICE_WEIGHT = 0.25
EFFECTIVENESS_BAND_HIGH_MIN = 0.8000
EFFECTIVENESS_BAND_MID_MIN = 0.6000

PER_VIOLATION_CENTS = 1_000_000
CONTINUING_DAILY_CENTS = 250_000
FORFEITURE_CAP_CENTS = 100_000_000
TIER_1_MAX_CENTS = 2_000_000
TIER_2_MAX_CENTS = 20_000_000

# Credit percentage by forfeiture tier and effectiveness band.
CREDIT_PERCENT = {
    "TIER_1": {"HIGH": 30, "MID": 15, "LOW": 5, "NONE": 0},
    "TIER_2": {"HIGH": 25, "MID": 10, "LOW": 5, "NONE": 0},
    "TIER_3": {"HIGH": 15, "MID": 5, "LOW": 0, "NONE": 0},
}

# ---------------------------------------------------------------------------
# Deadline offsets, expressed in hours
# ---------------------------------------------------------------------------
TRACEBACK_RESPONSE_DEADLINE_HOURS = 24
TRACEBACK_HARD_CUTOFF_HOURS = 72
NOTICE_MITIGATION_DEADLINE_HOURS = 48
DISPUTE_RESOLUTION_DEADLINE_HOURS = 24

# ---------------------------------------------------------------------------
# Sample E.164 numbers (NANP)
# ---------------------------------------------------------------------------
NUMBER_1 = "+12025550111"
NUMBER_2 = "+12025550222"
NUMBER_3 = "+12025550333"
NUMBER_4 = "+12025550444"
NUMBER_CALLED = "+12025550999"
NUMBER_CALLED_ALT = "+12025550888"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
