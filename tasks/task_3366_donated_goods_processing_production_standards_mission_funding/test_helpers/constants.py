"""Domain constants: calendar anchors, rates, thresholds, and the shared
standard fixture values used across the test suite (PRD sections 2.4, 2.6,
2.9, 3.2, 3.5, 3.6)."""

# --- Logical clock (PRD 2.4) -------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
WEEK_EPOCH_ISO = "2026-01-05T00:00:00Z"  # Monday anchor for week indices
# Week-aligned instants relative to the anchor: week N == anchor + N*7 days.
WEEK0_ISO = "2026-01-05T00:00:00Z"
WEEK1_ISO = "2026-01-12T00:00:00Z"
WEEK2_ISO = "2026-01-19T00:00:00Z"
WEEK3_ISO = "2026-01-26T00:00:00Z"
WEEK4_ISO = "2026-02-02T00:00:00Z"

# --- Retail week / color-tag cycle (PRD 2.4, 3.5) ----------------------------
COLORS = ["BLUE", "GREEN", "YELLOW", "RED"]
ROTATION_WEEKS = 4
MARKDOWN_PCT = [0, 25, 50, 75]

# --- Donor receipt condition multipliers (PRD 3.2) ---------------------------
CONDITION_MULTIPLIER = {"A": 1.0, "B": 0.75, "C": 0.5, "UNSALABLE": 0.0}

# --- Salvage channel pricing constants (PRD 3.6) -----------------------------
TEXTILE_RATE_CENTS_PER_LB = 12
MIN_BALE_LBS = 50
EWASTE_FEE_CENTS_PER_ITEM = 150
OUTLET_TIER1_LBS = 100
OUTLET_TIER1_RATE_CENTS = 45
OUTLET_TIER2_RATE_CENTS = 30

# --- Disposal per-material rates (PRD 3.6) -----------------------------------
DISPOSAL_RATE_CENTS_PER_LB = {"MIXED_UNSALABLE": 9, "HAZARD": 40, "FURNITURE": 15}

# --- Shared production-standard fixture shorthand ----------------------------
# TEXTILES standard: target 60 iph, hourly cost 1800 cents, price map
# A=1000 / B=700 / C=400, clamp floor 100, ceiling 5000.
STANDARD_FIXTURE = {
    "category": "TEXTILES",
    "target_items_per_hour": 60,
    "hourly_cost_cents": 1800,
    "grade_price_map": {"A": 1000, "B": 700, "C": 400},
    "price_floor_cents": 100,
    "price_ceiling_cents": 5000,
}
# STANDARD-variant unit cost locked at pricing: round_half_up(1800 / 60).
STANDARD_UNIT_COST_CENTS = 30
# Grade-A sale margin under the shared fixture: 1000 - 30.
GRADE_A_MARGIN_CENTS = 970

# --- Well-known mission-program window containing the default clock ----------
PROGRAM_START_ISO = "2026-01-01T00:00:00Z"
PROGRAM_END_ISO = "2026-12-31T00:00:00Z"
