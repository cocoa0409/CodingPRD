"""Domain thresholds and pinned numeric constants stated by the PRD."""

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
# The logical clock reads exactly this instant at startup.
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"
CANONICAL_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
    "MIN_OFFSET": 0,
}

# ---------------------------------------------------------------------------
# Declared defaults for optional inputs
# ---------------------------------------------------------------------------
DEFAULTS = {
    "MAX_SHOWS_PER_DAY": 2,
    "CURFEW_UTC_TIME": "23:30",
    "STRATEGY_BASIS": "ATTENDANCE_WEIGHTED",
    "CHANGEOVER_BUFFER_MINUTES": 120,
    "SLOT_SOFT_CAP": 3,
    "BASE_DRAW_SCORE": 50.00,
    "PRIOR_YEAR_PAID_ATTENDANCE": 0,
    "PRIOR_YEAR_NET_REVENUE_CENTS": 0,
    "BACKEND_BREAKEVEN_CENTS": 0,
    "RADIUS_MILES": 150,
    "RADIUS_DAYS_BEFORE": 30,
    "RADIUS_DAYS_AFTER": 30,
    "RESPONSE_WINDOW_HOURS": 48,
    "BUNDLED_WITH_GATE_ADMISSION": False,
    "FACILITY_FEE_CENTS": 0,
    "IS_CRITICAL": False,
    "ARTIST_RECOUPABLE": False,
    "SETTLEMENT_BASIS": "FINAL",
    "MERCH_GROSS_CENTS": 0,
    "MERCH_SELLER": "ARTIST",
    "REPLACEMENT_SHOW_DATE": None,
}

# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # Ticket gross potential and the bundled-ticket gate credit.
    "BUNDLE_CREDIT_RATIO": 0.60,
    "ADMISSION_TAX_RATE": 0.0575,
    # Negotiation
    "MAX_NEGOTIATION_ROUNDS": 3,
    # Genre adjacency: one calendar day either side of the candidate date.
    "GENRE_GAP_DAYS": 1,
    # Settlement waterfall
    "SPONSOR_OFFSET_SHARE": 0.25,
    "FLAT_PROMOTER_EXPENSE_CENTS": 2_500_000,
    "PRODUCTION_SURCHARGE_PCT": 0.035,
    # Merchandise split
    "MERCH_HALL_RATE_ARTIST": 0.20,
    "MERCH_HALL_RATE_VENUE": 0.30,
    "MERCH_ATTENDANCE_BONUS_RATE": 0.05,
    "MERCH_ATTENDANCE_TIER_SEATS": 2500,
    "MERCH_HALL_FEE_FLOOR_CENTS": 25_000,
    "MERCH_HALL_FEE_CAP_CENTS": 750_000,
    # Sponsorship activation premiums
    "STAGE_NAMING_PREMIUM_PCT": 0.25,
    "HIGH_DEMAND_PREMIUM_PCT": 0.10,
    "PRESENTING_TIER_PREMIUM_PCT": 0.05,
    "HIGH_DEMAND_GROSS_THRESHOLD_CENTS": 10_000_000,
    "MAX_PREMIUM_MULTIPLIER": 1.30,
    # Artist rescoring
    "ATT_BASE_WEIGHT": 0.60,
    "ATT_SELL_THROUGH_WEIGHT": 40.0,
    "REV_BASE_WEIGHT": 0.40,
    "REV_PER_SEAT_DIVISOR": 500,
    "REV_CONTRIBUTION_CAP": 60.0,
    "DRAW_SCORE_MIN": 0.00,
    "DRAW_SCORE_MAX": 100.00,
    # Buying-strategy report
    "GENRE_UNIVERSE_SIZE": 7,
    "SEGMENT_UNIVERSE_SIZE": 4,
    "NEXT_YEAR_UPLIFT": 1.10,
    "MAX_SINGLE_SHOW_SHARE": 0.35,
}

# ---------------------------------------------------------------------------
# Canonical fixture inputs. Every difficulty and corner scenario starts from
# these values unless it explicitly deviates.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "EDITION_YEAR": 2026,
    "EDITION_NAME": "State Fair 2026",
    "RUN_START_DATE": "2026-08-20",
    "RUN_END_DATE": "2026-08-30",
    "GATE_ADMISSION_PRICE_CENTS": 1500,
    "TALENT_BUDGET_CAP_CENTS": 40_000_000,
    "REFUND_RESERVE_CENTS": 15_000_000,
    "MAX_SHOWS_PER_DAY": 2,
    "CURFEW_UTC_TIME": "23:30",
    "STRATEGY_BASIS": "ATTENDANCE_WEIGHTED",
    "STAGE_NAME": "Grandstand",
    "RESERVED_SEAT_CAPACITY": 4000,
    "GA_CAPACITY": 6000,
    "CHANGEOVER_BUFFER_MINUTES": 120,
    "SLOT_SOFT_CAP": 4,
    "AGENT_USER_ID": "agent-hollis",
    "AGENCY_NAME": "Hollis Talent",
    "CONTACT_EMAIL": "book@hollis.example",
    "ARTIST_NAME": "Dust Road Revival",
    "ARTIST_GENRE": "COUNTRY",
    "ARTIST_AUDIENCE_SEGMENT": "FAMILY",
    "ARTIST_BASE_DRAW_SCORE": 62.50,
    "DEAL_TYPE": "VERSUS",
    "OFFERED_GUARANTEE_CENTS": 12_500_000,
    "BACKEND_SPLIT_PCT": 0.8500,
    "BACKEND_BREAKEVEN_CENTS": 6_000_000,
    "TARGET_SHOW_DATE": "2026-08-22",
    "LOAD_IN_START_UTC": "2026-08-22T14:00:00.000Z",
    "LOAD_OUT_END_UTC": "2026-08-22T23:00:00.000Z",
    "RESPONSE_WINDOW_HOURS": 48,
    "DOORS_TIME_UTC": "2026-08-22T18:00:00.000Z",
    "SEED_RIDER_DESCRIPTION": "Stage plot and rigging review",
}
