"""Domain thresholds and numeric constants from the PRD calculations."""

# Logical clock startup default (PRD §2.6): before any call the logical clock
# reads exactly 2026-09-01T00:00:00Z.
CLOCK_START = "2026-09-01T00:00:00Z"

# Resubmission hard cap (PRD §3.5): the REJECTED -> SUBMITTED cycle may repeat
# at most 3 times.
MAX_RESUBMITS = 3

# Certificate reissue grace window (PRD §3.6): 30 days after expires_at.
REISSUE_GRACE_DAYS = 30

# Contractor volume-bonus tiers (PRD §3.3).
TIER1_THRESHOLD_CENTS = 500000
TIER2_THRESHOLD_CENTS = 2000000
PRO_RATE = 0.02
PRO_PLUS_RATE = 0.05

# Standard store policy used across most setups (test driving convenience;
# mirrors the conventional configuration used throughout the PRD examples).
STANDARD_POLICY = {
    "submission_window_days": 30,
    "certificate_validity_months": 1,
    "expected_breakage_rate": 0.25,
    "split_txn_window_hours": 2,
    "split_txn_min_receipts": 3,
}

TEST_DEFAULTS = {
    "OWNER_NAME": "Ann Retail",
    "CONTRACTOR_NAME": "Carl Contractor",
    "WEEK_START": "2026-09-07",
    "WEEK_END": "2026-09-14",
}
