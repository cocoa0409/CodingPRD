"""Domain thresholds and closed-form helpers — numeric constants from PRD §2.4,
§3.1, and §3.5. Every value below is restated from PRD prose, not invented.

PRD §3.1: "The published average wage index begins at $10,000 for 1986 —
1,000,000 cents — and rises by $250 (25,000 cents) per year."
PRD §3.1: "The taxable maximum starts at $120,000 for 1986 — that is,
12,000,000 cents — and grows by $3,000 (300,000 cents) for each later year."
PRD §3.5: "For eligibility year 2024 the first bend point is $1,000 — 100,000
cents — and the second is $6,000 — 600,000 cents; each moves by $15 (1,500
cents) and $90 (9,000 cents) respectively for every year the eligibility year
differs from 2024."
PRD §3.5 (WEP): "a year is substantial when its `posted_earnings_cents` reach
that year's threshold: $9,000 for 1986 — 900,000 cents — rising by $225
(22,500 cents) per year."
"""

# --- logical clock (PRD §2.4) ----------------------------------------------
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- average wage index series (PRD §3.1) -----------------------------------
AWI_BASE_YEAR = 1986
AWI_BASE_CENTS = 1_000_000
AWI_STEP_CENTS_PER_YEAR = 25_000

# --- taxable maximum series (PRD §3.1) --------------------------------------
TAXABLE_MAX_BASE_CENTS = 12_000_000
TAXABLE_MAX_STEP_CENTS_PER_YEAR = 300_000

# --- PIA bend points (PRD §3.5) ---------------------------------------------
BEND_REFERENCE_YEAR = 2024
BEND1_BASE_CENTS = 100_000
BEND1_STEP_CENTS_PER_YEAR = 1_500
BEND2_BASE_CENTS = 600_000
BEND2_STEP_CENTS_PER_YEAR = 9_000

# --- WEP substantial-coverage series (PRD §3.5) ------------------------------
SUBSTANTIAL_BASE_CENTS = 900_000
SUBSTANTIAL_STEP_CENTS_PER_YEAR = 22_500
WEP_FULL_EXEMPTION_YOC = 30

# --- AIME (PRD §3.5) ---------------------------------------------------------
COMPUTATION_YEARS = 35
AIME_DIVISOR_MONTHS = 420  # 35 computation years times 12 months

# --- actuarial anchors (PRD §3.1, §3.4, §3.5) --------------------------------
FRA_MONTHS_BORN_1960_PLUS = 804
FRA_MONTHS_BORN_BEFORE_1960 = 792
MIN_CLAIM_AGE_MONTHS = 744        # exactly 62 years
SURVIVOR_MIN_AGE_MONTHS = 720     # exactly 60 years
SURVIVOR_FRA_MONTHS = 804
MAX_CLAIM_AGE_MONTHS = 840        # exactly 70 years (inclusive)

# --- windows (PRD §3.2, §3.4, §3.6, §3.8) -------------------------------------
WITHDRAWAL_WINDOW_MONTHS = 12
REOPEN_WINDOW_DAYS = 60
WAIVER_WINDOW_DAYS = 30
CORRECTION_STATUTE_MONTH_OFFSET = 4  # deadline = (tax_year+4)-04-15
CORRECTION_STATUTE_MONTH_DAY = "04-15"


def dime_floor(cents) -> int:
    """PRD §2.5: "a cent value is rounded *down* to the next lower multiple of
    ten cents."

    Accepts int or exact Fraction; never pass a float.
    """
    return int(cents // 10) * 10


def awi_cents(year: int) -> int:
    """Average wage index for `year` (PRD §3.1)."""
    return AWI_BASE_CENTS + AWI_STEP_CENTS_PER_YEAR * (year - AWI_BASE_YEAR)


def taxable_max_cents(year: int) -> int:
    """Annual contribution base for `year` (PRD §3.1)."""
    return TAXABLE_MAX_BASE_CENTS + TAXABLE_MAX_STEP_CENTS_PER_YEAR * (year - AWI_BASE_YEAR)


def bend1_cents(eligibility_year: int) -> int:
    """First PIA bend point for `eligibility_year` (PRD §3.5)."""
    return BEND1_BASE_CENTS + BEND1_STEP_CENTS_PER_YEAR * (eligibility_year - BEND_REFERENCE_YEAR)


def bend2_cents(eligibility_year: int) -> int:
    """Second PIA bend point for `eligibility_year` (PRD §3.5)."""
    return BEND2_BASE_CENTS + BEND2_STEP_CENTS_PER_YEAR * (eligibility_year - BEND_REFERENCE_YEAR)


def substantial_cents(year: int) -> int:
    """Substantial-coverage threshold for `year` (PRD §3.5 WEP)."""
    return SUBSTANTIAL_BASE_CENTS + SUBSTANTIAL_STEP_CENTS_PER_YEAR * (year - AWI_BASE_YEAR)
