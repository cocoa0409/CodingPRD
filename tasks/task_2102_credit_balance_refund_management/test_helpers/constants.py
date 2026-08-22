"""Domain thresholds and instants stated in the PRD."""

# The logical clock reads exactly this instant at server startup.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Instants reused across the scenario setups.
T_2026_08_01 = "2026-08-01T00:00:00Z"
T_2026_08_05 = "2026-08-05T00:00:00Z"
T_2026_08_06 = "2026-08-06T00:00:00Z"
T_2026_08_07 = "2026-08-07T00:00:00Z"
T_2026_08_10 = "2026-08-10T00:00:00Z"
T_2026_08_15 = "2026-08-15T00:00:00Z"
T_2026_08_16 = "2026-08-16T00:00:00Z"
T_2026_08_18 = "2026-08-18T00:00:00Z"
T_2026_08_20 = "2026-08-20T00:00:00Z"
T_2026_08_25 = "2026-08-25T00:00:00Z"
T_2027_02_16 = "2027-02-16T00:00:00Z"

THRESHOLDS = {
    # Refund preparation
    "MIN_REFUND_CENTS": 100,
    # De-minimis write-off ceiling on outstanding_cents
    "WRITE_OFF_LIMIT_CENTS": 1000,
    # Approval tiering
    "TIER_1_MAX_CENTS": 25_000,
    "TIER_2_MAX_CENTS": 250_000,
    "AGING_ESCALATION_DAYS": 181,
    "DE_ESCALATION_MAX_CENTS": 5_000,
    "MAX_TIER": 3,
    "MAX_REVISION_ROUNDS": 2,
    # Check processing fee bands
    "FEE_BAND_1_MAX_CENTS": 5_000,
    "FEE_BAND_1_BPS": 0,
    "FEE_BAND_1_FLAT_CENTS": 0,
    "FEE_BAND_2_MAX_CENTS": 50_000,
    "FEE_BAND_2_BPS": 150,
    "FEE_BAND_2_FLAT_CENTS": 100,
    "FEE_BAND_3_BPS": 75,
    "FEE_BAND_3_FLAT_CENTS": 500,
    "FEE_CAP_CENTS": 2_500,
    "MIN_CHECK_CENTS": 200,
    # Check staleness
    "CHECK_STALE_DAYS": 180,
    # Medicare 60-day repayment obligation
    "MEDICARE_REPAYMENT_WINDOW_DAYS": 60,
    "LATE_TIER_1_MAX_DAYS": 30,
    "LATE_TIER_1_RATE": 0.02,
    "LATE_TIER_2_MAX_DAYS": 90,
    "LATE_TIER_2_RATE": 0.05,
    "LATE_TIER_3_RATE": 0.10,
    # Take-back notices
    "DISPUTE_WINDOW_DAYS": 45,
    "STALE_DISPUTE_GRACE_DAYS": 30,
    # Unclaimed property
    "DORMANCY_DAYS_CA": 1_095,
    "DORMANCY_DAYS_TX": 1_095,
    "DORMANCY_DAYS_NY": 1_825,
    "DORMANCY_DAYS_FL": 1_825,
    "DUE_DILIGENCE_LEAD_DAYS": 120,
    # Compliance reports
    "REPORT_SEPARATION_DAYS": 7,
    # Credit balance aging bucket edges
    "AGING_D0_30_MAX": 30,
    "AGING_D31_60_MAX": 60,
    "AGING_D61_90_MAX": 90,
    "AGING_D91_180_MAX": 180,
    # Pagination
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

# Statuses that constitute open credit liability on a patient account.
OPEN_CREDIT_LIABILITY_STATUSES = [
    "IDENTIFIED",
    "UNDER_REVIEW",
    "ATTRIBUTED",
    "REFUND_PENDING",
]

# Check states whose gross amount counts toward CreditBalance.refunded_cents.
REFUNDED_COUNTED_CHECK_STATES = [
    "ISSUED",
    "CLEARED",
    "STALE",
    "REISSUED",
    "ESCHEATED",
]

TEST_DEFAULTS = {
    "CHARGE_CENTS": 50_000,
    "PAYMENT_CENTS": -62_000,
    "CREDIT_CENTS": 12_000,
    "PAYEE_ADDRESS_LINE": "1 Test Way",
}
