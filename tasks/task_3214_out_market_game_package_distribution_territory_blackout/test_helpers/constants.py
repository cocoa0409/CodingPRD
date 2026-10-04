"""Domain thresholds — numeric constants from the PRD's pricing and cap rules."""

# Server startup default logical-clock instant (PRD §1 note on time).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # Venue fee tier boundaries (PRD §3.8): inclusive upper bounds per tier.
    "T1_MAX_OCCUPANCY": 100,
    "T2_MAX_OCCUPANCY": 500,
    "T1_FEE_CENTS": 500000,
    "T2_FEE_CENTS": 2000000,
    "T3_FEE_CENTS": 6000000,
    # Hard cap on active multiview sessions per account (PRD §3.11).
    "MAX_MULTIVIEW_SESSIONS": 2,
    # Season structural bounds (PRD §3.2).
    "MAX_REGULAR_SEASON_WEEKS": 22,
    # Season policy knob defaults (PRD §3.2).
    "DEFAULT_GRACE_DAYS": 7,
    "DEFAULT_STUDENT_DISCOUNT_PCT": 50,
}

TEST_DEFAULTS = {
    # Shared scenario spine used across tests: grant cap, season shape, prices.
    "OCCUPANCY_CAP": 2000,
    "REGULAR_SEASON_WEEKS_18": 18,
    "SEASON_START_18W": "2026-08-05T00:00:00Z",
    "SEASON_END_18W": "2026-12-09T00:00:00Z",
    "BASE_PRICE_CENTS": 20000,
    "PREMIUM_PRICE_CENTS": 30000,
    "STUDENT_PRICE_CENTS": 16000,
    "OFFER_VALID_FROM": "2026-08-01T00:00:00Z",
    "OFFER_VALID_UNTIL": "2026-12-31T00:00:00Z",
    # Reference instants within week 4 of the 18-week season spine.
    "WEEK4_GAME_KICKOFF_EARLY": "2026-08-30T17:00:00Z",
    "WEEK4_GAME_KICKOFF_LATE": "2026-08-30T20:00:00Z",
    "WEEK5_GAME_KICKOFF": "2026-09-06T17:00:00Z",
}

# Nonexistent well-formed UUID used for 404 probes (distinct from framework's
# NON_EXISTENT_UUID so tests can choose either).
NONEXISTENT_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
