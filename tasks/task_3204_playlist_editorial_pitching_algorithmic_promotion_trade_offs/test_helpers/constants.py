"""Domain thresholds — numeric constants from the PRD (§3)."""
THRESHOLDS = {
    # Pitch timing (PRD §3.3)
    "MIN_PITCH_LEAD_DAYS": 7,
    "PITCH_WINDOW_DAYS": 7,
    # Pitch revision loop (PRD §3.3)
    "MAX_REVISION_ROUNDS": 2,
    # Release date changes (PRD §3.2)
    "MAX_DATE_CHANGES": 3,
    # Fraud strike limits (PRD §3.1)
    "FRAUD_STRIKE_LIMIT": 2,
    "TERMINATION_STRIKE_LIMIT": 3,
    # Fraud confidence thresholds (PRD §3.7)
    "FRAUD_AUTO_FLAG_THRESHOLD": 0.7000,
    "FRAUD_CONFIRM_THRESHOLD": 0.8500,
    # Clawback per-stream rate in cents (PRD §3.7)
    "PER_STREAM_RATE_CENTS": 0.40,
    # Boost score cap (PRD §3.8)
    "BOOST_CAP": 90,
    # Follower tiers (PRD §3.8)
    "FOLLOWER_TIER_LOW": 10000,
    "FOLLOWER_TIER_HIGH": 100000,
    # Track duration minimum (PRD §3.2)
    "MIN_TRACK_DURATION_MS": 30000,
    # Share base (PRD §2.8)
    "BPS_BASE": 10000,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "HOME_TERRITORY": "US",
    "DURATION_MS": 180000,
    "POOL_CENTS": 77777,
}
