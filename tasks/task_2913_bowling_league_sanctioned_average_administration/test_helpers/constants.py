"""Domain thresholds and the shared bylaw configuration used by the fixtures.

Every numeric constant here is stated verbatim in the PRD; nothing is invented.
"""

# ─── Sanction-fee pricing (PRD §3.3) ──────────────────
NATIONAL_FEE_ADULT_CENTS = 2600
NATIONAL_FEE_YOUTH_CENTS = 1200
LOCAL_ASSOCIATION_FEE_CENTS = 500
LATE_FILING_GRACE_DAYS = 21
LATE_PENALTY_CENTS = 1000

# ─── Averages and honor scores (PRD §3.2, §3.8) ───────
MIN_PRIOR_GAMES_FOR_CARRYOVER = 21
PERFECT_GAME_PINS = 300
HIGH_GAME_FLOOR = 298
SERIES_SCRATCH_FLOOR = 800
SERIES_HANDICAP_FLOOR = 700

# ─── Points and the prize waterfall (PRD §3.5, §3.7) ──
POINTS_PER_MATCH = 4
RESERVE_TIER_THRESHOLD_CENTS = 100_000
RESERVE_PCT_BELOW_TIER = 0.05
RESERVE_PCT_AT_OR_ABOVE_TIER = 0.08
ASSOCIATION_ADMIN_PCT = 0.03

# ─── Windows measured against the logical clock (PRD §2.4) ───
PROTEST_WINDOW_HOURS = 72
HONOR_SCORE_WINDOW_HOURS = 168
BOWLER_TRAVEL_BUFFER_MINUTES = 30

# ─── The logical clock's value before it has ever been set (PRD §2.4) ───
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ────────────────────────────
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ─── Instants used by the shared fixtures ─────────────
ORG_MEETING_INSTANT = "2026-08-05T00:00:00Z"
WEEK1_STARTS_AT = "2026-08-12T01:00:00Z"
WEEK1_ENDS_AT = "2026-08-12T03:00:00Z"
WEEK2_STARTS_AT = "2026-08-19T01:00:00Z"
WEEK2_ENDS_AT = "2026-08-19T03:00:00Z"
LANE_CERTIFIED_THROUGH = "2026-12-31T00:00:00Z"

# ─── The shared bylaw configuration the fixtures adopt by default ───
# Coherent under every PRD §2.7 cross-field rule:
#   prize_place_weights sum to 1.00, legal_lineup_minimum <= lineup_positions,
#   max_vacancy_slots_per_lineup < lineup_positions,
#   weekly_expense_cents <= weekly_dues_cents, vacancy_average <= handicap_base.
BASE_BYLAWS = {
    "handicap_base": 220,
    "handicap_percentage": 0.90,
    "handicap_percentage_youth": 0.80,
    "max_handicap_per_game": 60,
    "handicap_average_basis": "CURRENT",
    "minimum_games_for_average": 9,
    "carryover_policy": "BLENDED",
    "vacancy_average": 120,
    "vacancy_score": 120,
    "absentee_deduction": 10,
    "lineup_positions": 2,
    "legal_lineup_minimum": 2,
    "max_vacancy_slots_per_lineup": 1,
    "weekly_dues_cents": 1200,
    "weekly_expense_cents": 500,
    "max_dues_arrears_weeks": 2,
    "prize_place_weights": [0.60, 0.40],
}
