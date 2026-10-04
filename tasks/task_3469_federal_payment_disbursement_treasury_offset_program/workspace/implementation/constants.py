"""Domain constants for the Federal Payment Offset API.

Every value here traces to PRD.md or SCAFFOLD.yaml. No constant is invented.
"""
from decimal import Decimal

# --- Logical clock (PRD §2.4) ------------------------------------------------
# Before it is ever set, the clock reads exactly this instant and never falls
# back to wall-clock time.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- RBAC (PRD §2.1) ----------------------------------------------------------
ROLE_TREASURY_SUPERVISOR = "TreasurySupervisor"
ROLE_TREASURY_OPERATOR = "TreasuryOperator"
ROLE_PAYMENT_AGENCY_ANALYST = "PaymentAgencyAnalyst"
ROLE_CREDITOR_ANALYST = "CreditorAnalyst"
ROLE_STATE_COORDINATOR = "StateCoordinator"
ROLE_REFUND_OFFICER = "RefundOfficer"
ROLE_AUDITOR = "Auditor"

# System is the automation identity and is NEVER callable via X-User-Role.
DECLARED_ROLES = frozenset({
    ROLE_TREASURY_SUPERVISOR,
    ROLE_TREASURY_OPERATOR,
    ROLE_PAYMENT_AGENCY_ANALYST,
    ROLE_CREDITOR_ANALYST,
    ROLE_STATE_COORDINATOR,
    ROLE_REFUND_OFFICER,
    ROLE_AUDITOR,
})

AUTH_USER_ID_HEADER = "X-User-ID"
AUTH_USER_ROLE_HEADER = "X-User-Role"

# --- Pagination (PRD §2.3) ----------------------------------------------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# --- Enums --------------------------------------------------------------------
CREDITOR_TYPES = ("FEDERAL", "STATE")
TIN_TYPES = ("SSN", "EIN")
PAYMENT_TYPES = ("VENDOR", "SALARY", "BENEFIT_RETIREMENT", "BENEFIT_DISABILITY", "TAX_REFUND", "GRANT")
EXEMPTION_CLASSES = ("EXEMPT", "PARTIAL", "FULL")
DEBT_TYPES = ("CHILD_SUPPORT", "FEDERAL_TAX", "FEDERAL_NONTAX", "STATE_TAX", "STATE_OTHER")
PAYMENT_METHODS = ("EFT", "CHECK")
PROCESSING_STATUSES = ("VERIFIED", "HELD", "EVALUATED", "EXECUTED", "SETTLED", "REVERSED")
INTEGRITY_STATUSES = ("CLEAR", "FLAGGED")
DEBT_STATUSES = ("REFERRED", "NOTICED", "ACTIVE", "IN_COLLECTION", "PAID_IN_FULL", "RETURNED")
FILE_STATUSES = ("RECEIVED", "PROCESSING", "COMPLETED")
OFFSET_STATUSES = ("PROPOSED", "APPLIED", "REVERSED", "REFUNDED", "DROPPED")
CLAIM_STATUSES = ("FILED", "UNDER_REVIEW", "PAID", "DENIED", "APPEALED")
ACTION_TYPES = ("AWG", "CROSS_SERVICING")
ACTION_STATUSES = ("INITIATED", "ACTIVE", "COMPLETED", "TERMINATED")
REVERSE_STATUSES = ("MATCHED", "NO_MATCH", "CONFIRMED", "EXPIRED")
DIRECTIONS = ("FED_TO_STATE", "STATE_TO_FED", "BIDIRECTIONAL")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE")
POLICY_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
DNP_SOURCES = ("DEATH_MASTER_FILE", "SAM_EXCLUSION", "DEBARMENT_LIST")
DNP_STATUSES = ("ACTIVE", "REMOVED")
REFUND_REASONS = ("DEBT_NOT_OWED", "AMOUNT_INCORRECT", "PAYMENT_DUPLICATED", "DEBTOR_MISIDENTIFIED")
DECISIONS = ("APPROVE", "DENY")

# --- priority_rank mapping (SCAFFOLD calculations.priority_rank_mapping) ------
PRIORITY_RANK_BY_DEBT_TYPE = {
    "CHILD_SUPPORT": 10,
    "FEDERAL_TAX": 20,
    "FEDERAL_NONTAX": 30,
    "STATE_TAX": 40,
    "STATE_OTHER": 50,
}

# --- Offset pool (SCAFFOLD calculations.offset_pool_determination) ------------
CHILD_SUPPORT_PCT = Decimal("0.65")

# --- Remittance fee (PRD §2.9) ------------------------------------------------
REMIT_TIER_THRESHOLD_CENTS = 60000
REMIT_FEE_PCT_LOW_BAND = Decimal("0.03")
REMIT_FEE_PCT_HIGH_BAND = Decimal("0.02")

# --- AWG garnishment (SCAFFOLD calculations.awg_garnishment_amount) -----------
AWG_DISPOSABLE_PCT = Decimal("0.15")
AWG_WEEKLY_FLOOR_CENTS = 21750  # 30 x $7.25 federal minimum wage

# --- Temporal windows (PRD §3) -------------------------------------------------
NOTICE_WINDOW_DAYS = 30         # pre-offset notice window (§3.3)
AWG_HEARING_WINDOW_DAYS = 15    # garnishment hearing window (§3.7)
CLAIM_WINDOW_DAYS = 180         # refund claim filing window (§3.6)
APPEAL_WINDOW_DAYS = 30         # appeal window after decision (§3.6)
REVERSE_REQUEST_TTL_DAYS = 10   # reverse-offset request lifetime (§3.8)
