"""Domain thresholds and shared test literals from the PRD.

All money is integer cents, all proportions are integer basis points, and every
instant is a full ISO-8601 UTC instant. Player.birth_date is the only date-only
field in the contract.
"""

# ─── Logical clock ────────────────────────────────────────────────────────────
# The PRD pins the clock to this instant until a client sets it.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Shared season / window calendar used by the test fixtures ───────────────
SEASON_START_AT = "2026-08-01T00:00:00Z"
SEASON_END_AT = "2027-07-31T00:00:00Z"
ROSTER_LOCK_AT = "2026-09-15T00:00:00Z"
TRANSFER_WINDOW_OPEN_AT = "2026-08-05T00:00:00Z"
TRANSFER_WINDOW_CLOSE_AT = "2026-08-31T00:00:00Z"
CONTRACT_EFFECTIVE_AT = "2026-08-05T00:00:00Z"

# ─── League configuration defaults declared by the PRD ───────────────────────
LEAGUE_DEFAULTS = {
    "minimum_salary_cents": 3600000,
    "min_roster_size": 1,
    "max_roster_size": 7,
    "offer_response_window_hours": 72,
    "max_negotiation_rounds": 3,
    "player_association_levy_bp": 250,
    "association_min_prize_split_bp": 4000,
    "association_max_streaming_hours_per_week": 20,
    "minor_max_weekly_minutes": 1200,
    "adult_max_weekly_minutes": 2700,
    "education_reserved_minutes": 600,
    "minor_age_threshold_years": 18,
    "free_agency_cooldown_days": 14,
    "tryout_required_before_offer": False,
}

# ─── Organization defaults declared by the PRD ───────────────────────────────
ORG_DEFAULTS = {
    "annual_salary_budget_cents": 50000000,
    "org_prize_share_bp": 3500,
}

# ─── Team house defaults declared by the PRD ─────────────────────────────────
TEAM_HOUSE_DEFAULTS = {
    "turnaround_buffer_minutes": 60,
    "concurrent_seat_capacity": 10,
}

# ─── Numeric constants used by the PRD calculations ──────────────────────────
THRESHOLDS = {
    "HOUR_SECONDS": 3600,
    "DAY_SECONDS": 86400,
    "MONTH_DAYS": 30,
    "MONTHS_PER_YEAR": 12,
    "SEASON_DAYS": 365,
    "WEEK_DAYS": 7,
    "MINUTES_PER_HOUR": 60,
    "BP_DENOMINATOR": 10000,
    "DEFAULT_MINOR_AGE_THRESHOLD_YEARS": 18,
    "WEIGHT_PRACTICE_BP": 5000,
    "WEIGHT_LOAD_BP": 3000,
    "WEIGHT_STREAM_BP": 2000,
    "BURNOUT_WARN_THRESHOLD": 70,
    "BURNOUT_BREACH_THRESHOLD": 85,
    "WELLNESS_HOLD_DAYS": 7,
    "ROLLING_WINDOW_DAYS": 7,
    "RESIDENT_WITHHOLDING_BP": 1500,
    "NONRESIDENT_WITHHOLDING_BP": 3000,
    "MINOR_ESCROW_BP": 1000,
    "COMMISSION_TIER_BREAKPOINT_CENTS": 5000000,
    "COMMISSION_TIER_LOW_BP": 500,
    "COMMISSION_TIER_HIGH_BP": 300,
    "DEFAULT_TURNAROUND_BUFFER_MINUTES": 60,
}

# ─── Offer / contract money literals reused across the suite ─────────────────
TEST_DEFAULTS = {
    "BASE_SALARY_CENTS": 12500000,
    "SECOND_BASE_SALARY_CENTS": 10000000,
    "MINOR_BASE_SALARY_CENTS": 4000000,
    "TERM_MONTHS": 12,
    "PRIZE_SPLIT_PLAYER_PCT_BP": 4000,
    "STREAMING_HOURS_PER_WEEK": 10,
    "TAX_RESIDENCY_CODE": "US-CA",
    "SIGNING_BONUS_CENTS": 0,
    "BUYOUT_MULTIPLIER_BP": 5000,
    "GROSS_PRIZE_CENTS": 10000000,
    "DEAL_TOTAL_FEE_CENTS": 1000000,
}

# Prorated charge of a 12500000-cent salary effective 2026-08-05 in the shared
# season (360 remaining days of 365) and its full-season equivalent.
PROVISIONAL_CHARGE_12_5M = 12328767
FULL_SEASON_CHARGE_12_5M = 12500000
PROVISIONAL_CHARGE_10M = 9863014
PROVISIONAL_CHARGE_4M = 3945205

# ─── Identity literals for the opaque roles ──────────────────────────────────
LEAGUE_ADMIN_USER_ID = "admin-1"
SECOND_LEAGUE_ADMIN_USER_ID = "admin-2"
SCOUT_USER_ID = "scout-7"
COACH_USER_ID = "coach-3"
PERFORMANCE_SUPPORT_USER_ID = "support-5"
FINANCE_OFFICER_USER_ID = "finance-1"
SECOND_FINANCE_OFFICER_USER_ID = "finance-2"

# A syntactically valid identifier that never names a stored row.
MISSING_UUID = "00000000-0000-0000-0000-0000000000ff"
