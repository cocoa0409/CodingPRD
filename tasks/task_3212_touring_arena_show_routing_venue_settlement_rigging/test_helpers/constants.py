"""Domain thresholds — numeric constants from PRD calculations."""

HOLD_TTL_HOURS = 72
TRUCKS_PER_DOOR = 2
FAMILY_PACK_SIZE = 4

UNION_RULES = {
    "IATSE": {"minimum_hours": 4, "ot_threshold": 8, "ot_multiplier": 1.5},
    "TEAMSTERS": {"minimum_hours": 5, "ot_threshold": 10, "ot_multiplier": 1.5},
    "NON_UNION": {"minimum_hours": 1, "ot_threshold": 8, "ot_multiplier": 1.25},
}

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "SEASON_START": "2026-09-01T00:00:00Z",
    "SEASON_END": "2027-06-30T00:00:00Z",
    "AVAIL_OPENS": "2026-09-10T00:00:00Z",
    "AVAIL_CLOSES": "2026-09-15T00:00:00Z",
    "LOAD_IN": "2026-09-10T08:00:00Z",
    "FIRST_SHOW": "2026-09-11T19:00:00Z",
    "LOAD_OUT": "2026-09-13T23:00:00Z",
    "ON_SALE_AT": "2026-09-01T00:00:00Z",
    "DURING_PERFORMANCE_CLOCK": "2026-09-12T12:00:00Z",
    "DEFAULT_RENT_CENTS": 4_000_000,
    "PERCENTAGE_SHARE_PCT": 0.30,
    "MARKET_COOLDOWN_DAYS": 30,
}
