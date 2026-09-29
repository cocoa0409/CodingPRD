"""
Domain constants: the named thresholds, rates and defaults of the specification.

Every value here is quoted from the specification under test. Tests import these
names instead of restating literals so that a rate change is a one-line edit.
"""

# ── Logical clock ────────────────────────────────────
# The clock begins at exactly this instant when the server starts.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ── Pagination ───────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ── Paid miles and linehaul ──────────────────────────
MIN_PAID_MILES = 250            # short-haul floor
MILEAGE_BAND_BREAK = 500        # per-mile band break
LONG_HAUL_BUMP_CENTS = 3        # marginal bump above the band break
TEAM_SHARE_BPS = 5000           # COMPANY_TEAM linehaul share
MINUTES_PER_HOUR = 60

# ── Accessorial pricing ──────────────────────────────
DETENTION_FREE_MINUTES = 120
DETENTION_INCREMENT_MINUTES = 15
DETENTION_INCREMENT_CENTS = 500
DETENTION_CAP_CENTS = 20000
DETENTION_BUFFER_MINUTES = 15   # stored intervals are extended by this before overlap comparison
LAYOVER_DAILY_CENTS = 12500
LAYOVER_MAX_PAYABLE_DAYS = 3
STOP_OFF_CENTS = 5000
TARPING_FLAT_CENTS = 7500
TARPING_FLAT_UNITS = 1
BREAKDOWN_MINUTES_PER_DAY = 1440
BREAKDOWN_DAILY_CENTS = 10000

# ── Per diem ─────────────────────────────────────────
PER_DIEM_DAILY_CENTS = 6900
PER_DIEM_PCT_BPS = 2800
PER_DIEM_MAX_PCT_OF_GROSS_BPS = 4000

# ── Escrow ───────────────────────────────────────────
ESCROW_ACCRUAL_BPS = 800
ESCROW_RETURN_DAYS = 45
PERMISSIBLE_DEDUCTION_REASONS = [
    "ESCROW_FUNDING",
    "TRACTOR_LEASE",
    "INSURANCE_PREMIUM",
    "PERMIT_FEE",
    "CARGO_CLAIM_DAMAGE",
    "FUEL_TAX_TRUEUP",
]

# ── Advances ─────────────────────────────────────────
ADVANCE_RECOVERY_CAP_BPS = 2500
ADVANCE_OUTSTANDING_LIMIT_CENTS = 150000

# ── Corrections and disputes ─────────────────────────
RETRO_HOLD_THRESHOLD_CENTS = 50000
DISPUTE_WINDOW_DAYS = 30
DISPUTE_REOPEN_LIMIT = 2

# ── Basis-point denominator ──────────────────────────
BPS_DENOMINATOR = 10000
