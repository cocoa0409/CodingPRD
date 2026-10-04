"""Domain thresholds — numeric constants from the PRD's calculations."""

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
DEFAULT_TIME_ZONE = "America/Chicago"

RETAINAGE_PCT = 10

TOLERANCE_CENTS = {
    "PROPERTY_TAX": 0,
    "COURT_CASES": 0,
    "PAYROLL": 0,
    "ACCOUNTS_RECEIVABLE": 100,
    "LICENSES": 50,
}

READINESS_THRESHOLD = 80
WEIGHTS = {
    "milestones": 25,
    "migration": 25,
    "interfaces": 20,
    "uat": 15,
    "process": 10,
    "training": 5,
}

ESCALATOR_PCT = 3
LONG_TENURE_YEARS = 10

SLA_DAYS = {"SEV1": 1, "SEV2": 5, "SEV3": 20}
SLA_BREACH_ALLOWANCE = 2
WARRANTY_DAYS = 90
ROLLBACK_WINDOW_DAYS = 14
MAX_MILESTONE_REJECTIONS = 3

TEST_DEFAULTS = {
    "CONTRACT_VALUE_CENTS": 500_000_000,
    "SOLICITATION_NUMBER": "RFP-2026-001",
    "VENDOR_NAME": "TylerTech",
    "AGENCY_CODE": "REV",
    "AGENCY_NAME": "Dept of Revenue",
    "PHASE_START": "2026-10-01",
    "PHASE_END": "2026-12-31",
    "GO_LIVE_DATE": "2026-12-01",
}
