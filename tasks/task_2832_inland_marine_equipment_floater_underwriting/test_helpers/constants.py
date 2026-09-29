"""Numeric constants and canonical dates transcribed from the specification.

Everything here is a literal the specification names: the logical clock's
starting instant, the four territory expense loads, the valuation and theft
factor tables, the credit ladders, the transit and installation rates, the
catastrophe cutoffs, the grace period and the two referral thresholds.

Tests use these to spell an expectation in the same units the document uses;
the expected money in a test is always written out as a literal so that the
test states an answer rather than re-deriving one.
"""

# ─── The logical clock ────────────────────────────────────────────────────────

CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# ─── Policy defaults and term ─────────────────────────────────────────────────

DEFAULT_MINIMUM_PREMIUM_CENTS = 250000
DEFAULT_DEDUCTIBLE_CENTS = 100000

BASIS_POINT_SCALE = 10000
DAYS_PER_YEAR = 365

# ─── Territory expense loads (§ policy roll-up) ───────────────────────────────

EXPENSE_LOAD_BP = {
    "T1_COASTAL": 10800,
    "T2_URBAN": 10400,
    "T3_INLAND": 10200,
    "T4_REMOTE": 11200,
}

# ─── Valuation factors, shared by items and by the blanket variant ────────────

VALUATION_FACTOR_BP = {
    "ACV": 10000,
    "REPLACEMENT_COST": 11500,
    "AGREED_VALUE": 12500,
    "STATED_AMOUNT": 10800,
}

# ─── Theft factors keyed on the selected cell's hazard grade ───────────────────

THEFT_FACTOR_BP = {
    "A": 11800,
    "B": 11000,
    "C": 10400,
    "D": 10000,
}

# ─── Actual cash value depreciation ───────────────────────────────────────────

ACV_ANNUAL_DEPRECIATION_BP = 800
ACV_RETAINED_FLOOR_BP = 2000

DEFAULT_REPLACEMENT_COST_INDEX_BP = 11000
MIN_REPLACEMENT_COST_INDEX_BP = 10000

# ─── Credits on an equipment item ─────────────────────────────────────────────

CREDIT_CAP_BP = 2500
GEO_TRACKER_CREDIT_BP = {"A": 1500, "B": 1500, "C": 500, "D": 500}
JOBSITE_SECURITY_CREDIT_BP = {
    "TIER_0": 0,
    "TIER_1": 300,
    "TIER_2": 700,
    "TIER_3": 1200,
}

# ─── Jobsite security scoring ─────────────────────────────────────────────────

SECURITY_WEIGHTS = {
    "fenced": 1,
    "lighting": 1,
    "alarm_monitored": 1,
    "guarded_24h": 2,
}
SECURITY_TIER_CUTOFFS = [("TIER_3", 5), ("TIER_2", 3), ("TIER_1", 1), ("TIER_0", 0)]
MAX_SECURITY_SCORE = 5

# ─── The blanket variant ──────────────────────────────────────────────────────

BLANKET_LOAD_BP = 10600
COINSURANCE_CREDIT_BP = 500
COINSURANCE_CREDIT_THRESHOLD_BP = 9000
COINSURANCE_MIN_BP = 5000
COINSURANCE_MAX_BP = 10000

# ─── Installation floaters ────────────────────────────────────────────────────

FLOATER_ANNUAL_RATE_BP = 140
INSTALLATION_SECURITY_FACTOR_BP = {
    "TIER_0": 12500,
    "TIER_1": 11000,
    "TIER_2": 10000,
    "TIER_3": 9500,
}

# ─── Transit ──────────────────────────────────────────────────────────────────

TRANSIT_OWNED_RATE_BP = 65
TRANSIT_HIRED_RATE_BP = 95
CAT_TIER_2_FLOOR_CENTS = 65000
CAT_TIER_3_FLOOR_CENTS = 300000
CATASTROPHE_SURCHARGE_BP = {
    "CAT_TIER_1": 400,
    "CAT_TIER_2": 900,
    "CAT_TIER_3": 1400,
}
TURNAROUND_BUFFER_HOURS = 4

# ─── Reporting forms ──────────────────────────────────────────────────────────

REPORTING_GRACE_DAYS = 15
LATE_REPORTING_PENALTY_BP = 1000

# ─── Cancellation ─────────────────────────────────────────────────────────────

SHORT_RATE_RETAINED_BP = 9000

# ─── Referral thresholds ──────────────────────────────────────────────────────

REFERRAL_PREMIUM_THRESHOLD_CENTS = 5000000
REFERRAL_TIV_THRESHOLD_CENTS = 50000000

# ─── Claims ───────────────────────────────────────────────────────────────────

CONSTRUCTIVE_TOTAL_LOSS_BP = 7500
FULL_REPORTING_THRESHOLD_BP = 9000
NO_UNDERREPORTING_FACTOR_BP = 10000

# ─── Pagination ───────────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ─── Canonical term used by the fixtures ──────────────────────────────────────

TERM_EFFECTIVE_DATE = "2026-08-01"
TERM_EXPIRATION_DATE = "2027-08-01"
TERM_DAYS_ANNUAL = 365
