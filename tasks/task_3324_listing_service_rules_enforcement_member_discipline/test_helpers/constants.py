"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock boot default (PRD §2.4)
LOGICAL_CLOCK_BOOT = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # dues invoice late-fee tiers
    "LATE_TIER1_MAX_DAYS": 30,
    # clear-cooperation deadline: 24h after public_marketing_at (inclusive)
    "CLEAR_COOP_WINDOW_HOURS": 24,
    # status-change lateness grace (inclusive whole hours)
    "STATUS_CHANGE_GRACE_HOURS": 48,
    # strikes window and revert window
    "STRIKE_WINDOW_DAYS": 365,
    "REVERT_WINDOW_DAYS": 30,
    "ESCALATION_THRESHOLD": 3,
    # procuring-cause award tiers (score rounded to 2dp first)
    "TIER_FULL": 7.00,
    "TIER_HIGH": 5.00,
    "TIER_LOW": 3.00,
    # ethics sanction tiers in cents, indexed by strikes (0,1,2,>=3)
    "SANCTION_TIERS_CENTS": [50000, 100000, 250000, 500000],
    # hearing panel size
    "PANEL_SIZE": 3,
    # windows (days)
    "HEARING_REQUEST_WINDOW_DAYS": 20,
    "GRIEVANCE_SCREENING_DAYS": 45,
    "APPEAL_WINDOW_DAYS": 20,
    "CURE_WINDOW_DAYS": 30,
    "ARBITRATION_WINDOW_DAYS": 180,
    "TERMINATION_MIN_SUSPENDED_DAYS": 90,
    "LISTING_EXPIRY_DAYS": 365,
}

PROCURING_CAUSE_FACTOR_KEYS = [
    "F1_FIRST_CONTACT",
    "F2_CONTINUOUS_EFFORT",
    "F3_AGENCY_DISCLOSURE",
    "F4_CONTRACT_ROLE",
    "F5_ABANDONMENT",
]
PROCURING_CAUSE_WEIGHTS = [0.30, 0.25, 0.15, 0.20, 0.10]

TEST_DEFAULTS = {
    "MEMBERSHIP_DUES_CENTS": 120000,
    "LATE_FEE_TIER1_CENTS": 5000,
    "LATE_FEE_TIER2_CENTS": 15000,
    "SANCTION_CREDIT_CAP_CENTS": 200000,
    "FINE_INACCURACY_CENTS": 30000,
    "FINE_LATE_STATUS_CENTS": 25000,
    "FINE_CLEAR_COOP_CENTS": 40000,
    "FINE_FEED_ABUSE_CENTS": 25000,
}
