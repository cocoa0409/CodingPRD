"""Domain thresholds and constants from the PRD's arithmetic sections (§2.6, §3.3–§3.9)."""

# Logical clock startup default (PRD §2.11)
INITIAL_LOGICAL_CLOCK = "2026-09-01T00:00:00Z"

# ─── Rail fee schedule (PRD §3.3) ─────────────────────
THRESHOLDS = {
    "ACH_STANDARD_BASE_CENTS": 25,
    "ACH_SAME_DAY_BASE_CENTS": 500,
    "RTP_BASE_CENTS": 75,
    "RTP_TRANCHE_CENTS": 1_000_000,
    "RTP_TRANCHE_FEE_CENTS": 100,
    "WIRE_BASE_CENTS": 500,
    "WIRE_TRANCHE_CENTS": 1_000_000,
    "WIRE_TRANCHE_FEE_CENTS": 250,
    "CHECK_DEBIT_BASE_CENTS": 350,
    "CHECK_CREDIT_BASE_CENTS": 150,
    "CREDIT_ADJUSTMENT_CENTS": 25,
    "ACH_CAP_CENTS": 400,
    "WIRE_CAP_CENTS": 2500,
    "RTP_CAP_CENTS": 250,
    "FEE_FLOOR_CENTS": 10,
    "RETURN_LEG_FEE_CENTS": 25,
    # ─── Deposit attribution (PRD §3.8) ───────────────
    "FEE_FREE_BELOW_CENTS": 100_000,
    "DEPOSIT_MID_TIER_MAX_CENTS": 1_000_000,
    "MID_TIER_NUMERATOR": 10,
    "MID_TIER_DENOMINATOR": 1000,
    "MID_TIER_MIN_CENTS": 100,
    "HIGH_TIER_NUMERATOR": 5,
    "HIGH_TIER_DENOMINATOR": 1000,
    "HIGH_TIER_MIN_CENTS": 500,
    "HIGH_TIER_MAX_CENTS": 5000,
    # ─── Settlement pool health (PRD §3.9) ────────────
    "FORCED_FAILURE_BELOW_CENTS": 1_000_000,
    "DEGRADED_AT_OR_BELOW_CENTS": 5_000_000,
    # ─── Velocity limit (PRD §3.5) ────────────────────
    "PLATFORM_DEFAULT_LIMIT_CENTS": 5_000_000,
    # ─── Duplicate window (PRD §3.10) ─────────────────
    "DUP_WINDOW_SECONDS": 600,
    # ─── Return conditional cascade (PRD §3.5) ────────
    "RETURN_RESTRICTION_THRESHOLD_CENTS": 100_000,
    # ─── Exception aging (PRD §3.8) ───────────────────
    "AGING_CURRENT_MAX_DAYS": 1,
    "AGING_AGING_MAX_DAYS": 3,
    "AGING_ESCALATED_MAX_DAYS": 7,
    # ─── Calendar / period (PRD §3.4, §3.9) ───────────
    "LOOKAHEAD_CALENDAR_DAYS": 4,
    "PERIOD_CLOSE_INDEX": 12,
}

TEST_DEFAULTS = {
    "LEDGER_NAME": "Ops Ledger",
    "PLATFORM_ADMIN_ID": "test-platform-admin-1",
    "LEDGER_CONTROLLER_ID": "test-ledger-controller-1",
    "PAYMENT_INITIATOR_ID": "test-initiator-1",
    "PAYMENT_APPROVER_ID": "test-approver-1",
    "PAYMENT_OPS_ANALYST_ID": "test-analyst-1",
    "PAYMENT_OPS_APPROVER_ID": "test-ops-approver-1",
    "AUDITOR_ID": "test-auditor-1",
    "INSTITUTION_NAME": "Northwind Payments",
    "INSTITUTION_SHORT_CODE": "NWP",
    "COUNTERPARTY_NAME": "Delta Supply Co",
    "COUNTERPARTY_EXTERNAL_REF": "DS-1",
    "BANK_INSTITUTION_NAME": "First Meridian",
    "ROUTING_NUMBER": "021000021",
    "ACCOUNT_NUMBER_LAST4": "4321",
    "SUPPORTED_RAILS": ["ACH", "WIRE", "RTP"],
    "AVAILABLE_FUNDS_CENTS": 4_000_000,
    "TIMEZONE": "America/New_York",
    "ACCOUNT_BALANCE": 0,
}

# A syntactically valid but unallocated id, used for not-found paths.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"