"""Domain thresholds and constants.

Every value below is taken verbatim from the PRD prose (Sections 2 and 3);
each was diffed against the PRD text before being written here.
"""

# --- Logical clock (PRD §2.5) -------------------------------------------------
# "At startup the logical clock reads exactly 2026-09-01T00:00:00Z, and it
# never falls back to wall-clock time."
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Fleet lease rate (PRD §3.4) ----------------------------------------------
# "A tier multiplier follows the course's cut_quality_standard: 1.15 for
# CHAMPIONSHIP, 1.08 for CLUB, and 1.00 for MAINTENANCE."
TIER_MULTIPLIER_CHAMPIONSHIP = 1.15
TIER_MULTIPLIER_CLUB = 1.08
TIER_MULTIPLIER_MAINTENANCE = 1.00
# "A seasonal factor of 1.06 applies when the month of start_date is March,
# April, or May — the spring delivery peak — and 1.00 otherwise."
SPRING_PEAK_MONTHS = (3, 4, 5)
SPRING_PEAK_FACTOR = 1.06

# --- Trade-in valuation (PRD §3.5) --------------------------------------------
# "the reported hours divided by a monthly usage norm of 50 hours per month,
# rounded down to a whole month count"
MONTHLY_HOURS_NORM = 50
# "one minus the ratio of age_months to an 84-month depreciation schedule"
BOOK_DEPRECIATION_MONTHS = 84
# "a residual floor of 15 percent of list_price_cents"
BOOK_RESIDUAL_FLOOR_PCT = 0.15
# "market_value_cents is list_price_cents times 60 percent times the condition
# multiplier times the hours factor"
MARKET_BASE_PCT = 0.60
# "an hours factor starts at 1 and decays by half across the first 4,000 hours
# of use — precisely, one minus the product of 0.50 and the ratio of the
# smaller of hours and 4,000 to 4,000"
MARKET_HOURS_CAP = 4000
MARKET_HOURS_DECAY_PCT = 0.50
# "a condition multiplier of 1.00 for grade A, 0.85 for B, 0.70 for C, or
# 0.50 for D"
CONDITION_MULTIPLIER_A = 1.00
CONDITION_MULTIPLIER_B = 0.85
CONDITION_MULTIPLIER_C = 0.70
CONDITION_MULTIPLIER_D = 0.50
CONDITION_MULTIPLIERS = {
    "A": CONDITION_MULTIPLIER_A,
    "B": CONDITION_MULTIPLIER_B,
    "C": CONDITION_MULTIPLIER_C,
    "D": CONDITION_MULTIPLIER_D,
}

# --- Off-season parts incentive (PRD §3.3) ------------------------------------
# "The incentive applies only when the order is STOCK and the logical clock's
# month is November, December, January, or February."
OFF_SEASON_MONTHS = (11, 12, 1, 2)
# "a subtotal of at least 200,000 cents earns 12 percent; otherwise a subtotal
# of at least 50,000 cents earns 7 percent; otherwise 3 percent"
INCENTIVE_TIER2_THRESHOLD_CENTS = 200000
INCENTIVE_TIER2_PCT = 0.12
INCENTIVE_TIER1_THRESHOLD_CENTS = 50000
INCENTIVE_TIER1_PCT = 0.07
INCENTIVE_BASE_PCT = 0.03

# --- Warranty adjudication (PRD §3.8) -----------------------------------------
# "Parts are reimbursed at cost plus a 10 percent handling allowance"
PARTS_HANDLING_PCT = 0.10

# --- Parts stocking compliance (PRD §3.1) -------------------------------------
# "The review passes when the fill rate is at least 0.92 — the boundary is
# inclusive"
MIN_FILL_RATE = 0.92
# "over a trailing 365-day window ending on the review date"
REVIEW_WINDOW_DAYS = 365

# --- Remarketing pricing (PRD §3.7) -------------------------------------------
# "The initial ask ... is 55 percent of the model's list_price_cents scaled by
# the return condition_grade's multiplier"
REMARKET_BASE_PCT = 0.55
# "reducing asking_price_cents by 2 percent with round-half-up at every step"
REMARKET_DECAY_PCT = 0.02
# "The floor_price_cents ... is 60 percent of that initial ask"
REMARKET_FLOOR_PCT = 0.60
# "sets reservation_expires_at to the logical clock plus a 7-day hold"
RESERVATION_HOLD_DAYS = 7

# --- Irrigation design spec (PRD §3.9) ----------------------------------------
# "controllers_required is the zone_count divided by 8 zones per controller,
# rounded up"
ZONES_PER_CONTROLLER = 8
# "a base design fee of 250,000 cents, plus 45,000 cents per required
# controller, plus 12,000 cents per irrigated acre"
BASE_DESIGN_FEE_CENTS = 250000
CONTROLLER_FEE_CENTS = 45000
ACRE_FEE_CENTS = 12000
# "22,000 for BENTGRASS, 16,000 for BERMUDA, 20,000 for POA_ANNUA, and 18,000
# for MIXED"
GPD_PER_ACRE_BENTGRASS = 22000
GPD_PER_ACRE_BERMUDA = 16000
GPD_PER_ACRE_POA_ANNUA = 20000
GPD_PER_ACRE_MIXED = 18000
GPD_PER_ACRE = {
    "BENTGRASS": GPD_PER_ACRE_BENTGRASS,
    "BERMUDA": GPD_PER_ACRE_BERMUDA,
    "POA_ANNUA": GPD_PER_ACRE_POA_ANNUA,
    "MIXED": GPD_PER_ACRE_MIXED,
}

# --- Equipment spec compliance (PRD §3.4) -------------------------------------
# "a CHAMPIONSHIP course admits only TOURNAMENT-tier models; a CLUB course
# admits TOURNAMENT or PRO; a MAINTENANCE course admits TOURNAMENT, PRO, or
# STANDARD"
SPEC_REQUIRED_TIERS = {
    "CHAMPIONSHIP": ("TOURNAMENT",),
    "CLUB": ("TOURNAMENT", "PRO"),
    "MAINTENANCE": ("TOURNAMENT", "PRO", "STANDARD"),
}

# --- Catalog aging (PRD §3.2) -------------------------------------------------
# "a model whose age strictly exceeds 240 months — a twenty-year sales window —
# is moved to DISCONTINUED"
MODEL_SALES_WINDOW_MONTHS = 240

# --- Pagination (PRD §2.3) ----------------------------------------------------
# "when not provided it defaults to 10, with a minimum of 1 and a maximum of
# 100. offset sets the number of items to skip and defaults to 0"
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0
