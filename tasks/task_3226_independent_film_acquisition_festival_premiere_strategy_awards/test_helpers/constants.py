"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# premiere_cachet
PRESTIGE_POINTS = {"A_LIST": 100, "B_LIST": 60, "REGIONAL": 30}
SECTION_BONUS = {"COMPETITION": 40, "PREMIERES": 25, "MIDNIGHT": 15, "NEXT": 10}
EMBARGO_TIER_1_MAX_HOURS = 12     # delay <= 12h  -> multiplier 1.25
EMBARGO_TIER_2_MAX_HOURS = 48     # 12 < delay <= 48h -> multiplier 1.00
# delay > 48h -> multiplier 0.75
EMBARGO_MAX_HOURS = 168           # one-week sanity cap on embargo delay

# platform_expansion
WIDE_SCREEN_THRESHOLD = 600

# campaign_eligible_spend
CAP_PCT = {
    "SCREENING": 0.40,
    "GUILD_MAILER": 0.25,
    "PUBLICITY": 0.30,
    "TRAVEL": 0.15,
    "EVENT": 0.20,
}
INDIE_TRAVEL_CAP_CENTS = 25_000_000

# participation_waterfall
DIST_FEE_PCT_GROSS = 0.15
DIST_FEE_PCT_NET = 0.30

# talent_travel_conflict
TRAVEL_BUFFER_HOURS = 6

# Clock default
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
