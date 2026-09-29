"""Domain numbers the PRD pins: rates, percentages, thresholds and defaults.

Every monetary figure here is an integer number of whole cents.
"""

# ─── Per-term rental rates by unit class (cents) ──────────────────────────
UNIT_TERM_RATE_CENTS = {
    "STANDARD_PORTABLE": 14500,
    "ADA_PORTABLE": 22500,
    "HANDWASH_STATION": 9500,
    "TRAILER_2STALL": 78000,
    "TRAILER_8STALL": 265000,
}

# ─── Per-visit service cost by unit class (cents) ─────────────────────────
UNIT_PER_VISIT_SERVICE_COST_CENTS = {
    "STANDARD_PORTABLE": 4200,
    "ADA_PORTABLE": 5600,
    "HANDWASH_STATION": 2600,
    "TRAILER_2STALL": 17500,
    "TRAILER_8STALL": 52000,
}

# ─── Damage replacement basis by unit class (cents) ───────────────────────
UNIT_REPLACEMENT_BASIS_CENTS = {
    "STANDARD_PORTABLE": 32000,
    "ADA_PORTABLE": 48000,
    "HANDWASH_STATION": 19000,
    "TRAILER_2STALL": 145000,
    "TRAILER_8STALL": 390000,
}

DAMAGE_SEVERITY_PCT = {"MINOR": 40, "MODERATE": 75, "TOTAL_LOSS": 100}
TIP_OVER_BASE_CENTS = 27500
TIP_OVER_SEVERITY_PCT = 100

# Strike multiplier: prior total of damage_strikes + tip_over_count.
STRIKE_MULTIPLIER_PCT = {"ZERO_OR_ONE": 100, "EXACTLY_TWO": 150, "THREE_OR_MORE": 200}

# ─── Relocation pricing ───────────────────────────────────────────────────
RELOCATION_BASE_CENTS = 18500
ACCESS_CLASS_MULTIPLIER_PCT = {
    "OPEN_LOT": 100,
    "GATED": 115,
    "STAIR_ACCESS": 140,
    "CRANE_ONLY": 225,
}
SAME_DAY_UPLIFT_PCT = 35

# ─── Missed-service credit ────────────────────────────────────────────────
# Walked in order; the first tier whose ceiling is >= the planned-density
# snapshot supplies the surcharge percentage.
DENSITY_SURCHARGE_TIERS = [(40, 12.0), (75, 6.0), (100, 0.0)]
MISSED_SERVICE_CREDIT_PCT = 115

# ─── Invoice escalation percentages ───────────────────────────────────────
SEASON_ESCALATION_PCT = {"PEAK": 8.5, "SHOULDER": 3.25, "OFF": 0.0}
PHASE_ESCALATION_PCT = {
    "SITEWORK": 0.0,
    "VERTICAL": 4.75,
    "FINISHES": 2.5,
    "EVENT_NA": 0.0,
}
FUEL_SURCHARGE_PCT = 1.75

# ─── Sizing constants ─────────────────────────────────────────────────────
EVENT_PEAK_ALLOWANCE_NUMERATOR = 12
EVENT_PEAK_ALLOWANCE_DENOMINATOR = 10
CONSTRUCTION_SHIFT_HOURS = 9
PERSON_HOURS_PER_STANDARD_UNIT = 250
TRAILER_HEADCOUNT_FLOOR = 400
ADA_MIN_UNITS = 1
ADA_UNITS_PER_RESTROOM_EQUIVALENTS = 20
HANDWASH_RESTROOM_POSITIONS_PER_STATION = 4

# ─── Operational thresholds ───────────────────────────────────────────────
ACCOUNT_CREDIT_HOLD_THRESHOLD_CENTS = 60000
UNIT_REPAIR_STRIKE_THRESHOLD = 3
PERMIT_MAX_REVISION_ROUNDS = 3
CHARGE_DISPUTE_WINDOW_DAYS = 14
ROUTE_TURNAROUND_BUFFER_MINUTES = 20

# ─── Declared field ranges and defaults ───────────────────────────────────
CREDIT_TERMS_DAYS_ALLOWED = [0, 15, 30, 45]
DEFAULT_CREDIT_TERMS_DAYS = 30
DEFAULT_GATE_OPEN_MINUTE = 0
DEFAULT_GATE_CLOSE_MINUTE = 1440
DEFAULT_MAX_TRUCK_LENGTH_FT = 24
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# ─── The logical clock ────────────────────────────────────────────────────
# Before the clock is ever repositioned it reads exactly this instant.
CLOCK_INITIAL_INSTANT = "2026-08-01T00:00:00.000Z"
CLOCK_INITIAL_DATE = "2026-08-01"

# Mondays used by the route fixtures, and the reference repositioning points.
CLOCK_MONDAY_MORNING = "2026-08-03T08:00:00Z"
CLOCK_MONDAY_MORNING_CANONICAL = "2026-08-03T08:00:00.000Z"
CLOCK_SECOND_MONDAY_EARLY = "2026-08-10T06:00:00Z"
CLOCK_SECOND_MONDAY_EARLY_CANONICAL = "2026-08-10T06:00:00.000Z"
MONDAY_FIRST = "2026-08-03"
MONDAY_SECOND = "2026-08-10"
MONDAY_THIRD = "2026-08-17"

TEST_DEFAULTS = {
    "TERM_START": "2026-08-03",
    "TERM_END": "2026-09-30",
    "PERMIT_EFFECTIVE_FROM": "2026-08-01",
    "PERMIT_EFFECTIVE_TO": "2026-12-31",
    "ROUTE_CAPACITY_UNITS": 20,
    "ROUTE_WASTE_GALLONS": 3000,
}
