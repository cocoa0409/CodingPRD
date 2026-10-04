"""Domain thresholds — numeric constants from the PRD calculations."""

# Logical clock startup default (PRD §2.6).
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# Royalty tiers (PRD §3.3): marginal cents-per-record bands.
ROYALTY_TIER1_MAX = 10000          # records 1..10000 earn 0 cents each
ROYALTY_TIER2_MAX = 50000          # records 10001..50000 earn 3 cents each
ROYALTY_TIER2_RATE_CENTS = 3
ROYALTY_TIER3_RATE_CENTS = 5       # records beyond 50000 earn 5 cents each
QA_BONUS_THRESHOLD = 0.98          # deid_qa_score >= 0.98 earns the bonus
QA_BONUS = 0.10                    # +10 percent royalty bonus
ROYALTY_MULTIPLIER = {
    "PHARMACY": 1.0,
    "DISTRIBUTOR": 0.6,
    "CLAIM_PROCESSOR": 0.8,
}

# Acceptance QA floor (PRD §3.3): deid_qa_score must be at least 0.90.
DEID_QA_ACCEPT_FLOOR = 0.90

# Invoice preview discount tiers (PRD §3.6), in cents of gross.
INVOICE_TIER1_MIN = 20000
INVOICE_TIER2_MIN = 50000

# SLA credit (PRD §3.7): per-breach rate and cap, as fractions of the
# product's monthly license fee.
SLA_PER_BREACH_RATE = 0.05
SLA_CREDIT_CAP_RATE = 0.25

# Audit cooldown (PRD §3.8): whole days between completed audit end and the
# new window start; exactly 30 passes.
AUDIT_COOLDOWN_DAYS = 30

TEST_DEFAULTS = {
    "ENTITLEMENT_CELLS_TOTAL": 100,
    "ROYALTY_BUDGET_CENTS": 1000000,
    "RECORD_COUNT": 20000,
    "BASE_FEE_CENTS": 10000,
    "CELL_FEE_BASE_CENTS": 1000,
    "CELL_FEE_MULTIPLIER": 1.0,
    "VOLUME_DISCOUNT_PCT": 0.0,
    "MONTHLY_LICENSE_FEE_CENTS": 200000,
}
