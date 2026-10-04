"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Booking-mode wellness bands (PRD §3.1); boundaries are inclusive.
    "WELLNESS_BOOKABLE_MIN": 70.0,
    "WELLNESS_LIMITED_MIN": 40.0,
    # Wellness accrual (PRD §3.6).
    "FULFILLED_DELTA": 3.0,
    "NOSHOW_DELTA": -8.0,
    "WEEKLY_DECAY": 1.0,
    "WELLNESS_MIN": 0.0,
    "WELLNESS_MAX": 100.0,
    # Royalty tiering (PRD §3.8), in integer cents / basis points.
    "TIER1_GROSS_CENTS": 100000,
    "TIER2_GROSS_CENTS": 250000,
    "TIER2_BONUS_BP": 200,
    "TIER0_DISCOUNT_BP": 100,
    "ROYALTY_RATE_MAX_BP": 5000,
    # Storyline gap rule (PRD §3.4).
    "GAP_SHELF_THRESHOLD": 3,
    # Distribution windowing (PRD §3.7).
    "LIVE_PREOPEN_MINUTES": 30,
    "REPLAY_DELAY_HOURS": 24,
    # Injury scratch horizon (PRD §3.10).
    "INJURY_SCRATCH_HORIZON_DAYS": 30,
    # Call-up readiness (PRD §3.12).
    "CALLUP_TRAILING_DAYS": 90,
    "PROMOTE_THRESHOLD": 60,
}

TEST_DEFAULTS = {
    "ROYALTY_RATE_BP": 2000,
    "DOWNSIDE_GUARANTEE_CENTS": 100000,
    "DEFAULT_CLOCK": "2026-09-01T00:00:00Z",
}

# A well-formed UUID that never resolves to an existing resource.
NONEXISTENT_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
