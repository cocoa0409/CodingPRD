"""Domain constants — every value derived verbatim from the PRD.

Sources:
  - PRD §2.3  pagination defaults (limit 10, min 1, max 100, offset 0)
  - PRD §2.4  logical clock default 2026-09-01T00:00:00Z
  - PRD §2.9  remittance fee tiers (3% below 60000 cents YTD, else 2%)
  - PRD §3.3  notice window 30 days; priority ranks per debt_type
  - PRD §3.4  child-support percentage branch 0.65
  - PRD §3.6  claim window 180 days; appeal window 30 days
  - PRD §3.7  AWG garnishment 15%; weekly floor 21750 cents; hearing window 15 days
  - PRD §3.8  reverse-offset request TTL 10 days
"""

# --- Logical clock (PRD §2.4) -------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# --- Pagination (PRD §2.3) ----------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Temporal windows (PRD §3.3, §3.6, §3.7, §3.8) -----------------------------
NOTICE_WINDOW_DAYS = 30          # debt activate: clock >= notice_sent_at + 30 days
AWG_HEARING_WINDOW_DAYS = 15     # AWG activate: clock >= notice_sent_at + 15 days
CLAIM_WINDOW_DAYS = 180          # refund claim within 180 days of Offset.applied_at
APPEAL_WINDOW_DAYS = 30          # appeal within 30 days of RefundClaim.decided_at
REVERSE_REQUEST_TTL_DAYS = 10    # expires_at = created_at + 10 days

# --- Remittance fee tiers (PRD §2.9) -------------------------------------------
REMIT_TIER_THRESHOLD_CENTS = 60000   # pre-event YTD gross below this -> 3% band
REMIT_FEE_PCT_LOW_BAND = 0.03        # three percent
REMIT_FEE_PCT_HIGH_BAND = 0.02       # two percent

# --- Offset pool (PRD §3.4) ----------------------------------------------------
CHILD_SUPPORT_PCT = 0.65   # applies when any eligible matched debt is CHILD_SUPPORT

# --- AWG garnishment (PRD §3.7) ------------------------------------------------
AWG_DISPOSABLE_PCT = 0.15          # fifteen percent of disposable pay
AWG_WEEKLY_FLOOR_CENTS = 21750     # 30 hours x $7.25 federal minimum wage

# --- Debt priority ranks (PRD §3.3) --------------------------------------------
PRIORITY_RANKS = {
    "CHILD_SUPPORT": 10,
    "FEDERAL_TAX": 20,
    "FEDERAL_NONTAX": 30,
    "STATE_TAX": 40,
    "STATE_OTHER": 50,
}
RANK_CHILD_SUPPORT = 10
RANK_FEDERAL_TAX = 20
RANK_FEDERAL_NONTAX = 30
RANK_STATE_TAX = 40
RANK_STATE_OTHER = 50

# --- Enum value sets (PRD §2.1, §3.1, §3.2, §3.3, §3.6, §3.7, §3.8, §2.10, §2.11)
CREDITOR_TYPES = ("FEDERAL", "STATE")
TIN_TYPES = ("SSN", "EIN")
PAYMENT_TYPES = (
    "VENDOR", "SALARY", "BENEFIT_RETIREMENT",
    "BENEFIT_DISABILITY", "TAX_REFUND", "GRANT",
)
EXEMPTION_CLASSES = ("EXEMPT", "PARTIAL", "FULL")
DEBT_TYPES = (
    "CHILD_SUPPORT", "FEDERAL_TAX", "FEDERAL_NONTAX", "STATE_TAX", "STATE_OTHER",
)
PAYMENT_METHODS = ("EFT", "CHECK")
PAYMENT_PROCESSING_STATUSES = (
    "VERIFIED", "HELD", "EVALUATED", "EXECUTED", "SETTLED", "REVERSED",
)
PAYMENT_INTEGRITY_STATUSES = ("CLEAR", "FLAGGED")
PAYMENT_FILE_STATUSES = ("RECEIVED", "PROCESSING", "COMPLETED")
DEBT_STATUSES = (
    "REFERRED", "NOTICED", "ACTIVE", "IN_COLLECTION", "PAID_IN_FULL", "RETURNED",
)
OFFSET_STATUSES = ("PROPOSED", "APPLIED", "REVERSED", "REFUNDED", "DROPPED")
REFUND_CLAIM_STATUSES = ("FILED", "UNDER_REVIEW", "PAID", "DENIED", "APPEALED")
REFUND_REASONS = (
    "DEBT_NOT_OWED", "AMOUNT_INCORRECT", "PAYMENT_DUPLICATED", "DEBTOR_MISIDENTIFIED",
)
REFUND_DECISIONS = ("APPROVE", "DENY")
COLLECTION_ACTION_TYPES = ("AWG", "CROSS_SERVICING")
COLLECTION_ACTION_STATUSES = ("INITIATED", "ACTIVE", "COMPLETED", "TERMINATED")
AGREEMENT_DIRECTIONS = ("FED_TO_STATE", "STATE_TO_FED", "BIDIRECTIONAL")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE")
DNP_LIST_SOURCES = ("DEATH_MASTER_FILE", "SAM_EXCLUSION", "DEBARMENT_LIST")
DNP_STATUSES = ("ACTIVE", "REMOVED")
REVERSE_REQUEST_STATUSES = ("MATCHED", "NO_MATCH", "CONFIRMED", "EXPIRED")
POLICY_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")

CALLABLE_ROLES = (
    "TreasurySupervisor", "TreasuryOperator", "PaymentAgencyAnalyst",
    "CreditorAnalyst", "StateCoordinator", "RefundOfficer", "Auditor",
)
NEVER_CALLABLE_ROLES = ("System",)

# --- Test-data defaults used across fixtures (values chosen, not PRD-pinned) ----
DEFAULT_NOTICE_SENT_AT = "2026-08-01T00:00:00Z"   # 30+ days before the default clock
DEFAULT_DELINQUENT_SINCE = "2026-01-15T00:00:00Z"
DEFAULT_SETTLEMENT_DATE = "2026-09-15T00:00:00Z"
DEFAULT_AGREEMENT_WINDOW = ("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
DEFAULT_DNP_WINDOW = ("2026-08-01T00:00:00Z", "2027-08-01T00:00:00Z")
