"""Benefit arithmetic (SCAFFOLD.yaml §1.3 / PRD §2.5 and §3.5).

All money is integer cents. Intermediate arithmetic is exact rational
(fractions.Fraction); rounding is applied only where a rule states it:
  * round-half-up to whole cents — wage indexation only;
  * dime_floor(x) = floor(x / 10) * 10 — PIA, family maximum, spousal and
    survivor amounts, GPO, age-adjusted benefits, COLA, proportional shares.
No float is ever used for money.
"""

from fractions import Fraction
from math import floor

# --- pinned constants (scaffold §1.3) ---------------------------------------
AWI_BASE_YEAR = 1986
AWI_BASE_CENTS = 1_000_000
AWI_STEP_CENTS_PER_YEAR = 25_000
TAXABLE_MAX_BASE_CENTS = 12_000_000
TAXABLE_MAX_STEP_CENTS_PER_YEAR = 300_000
BEND1_BASE_CENTS = 100_000
BEND1_STEP_CENTS_PER_YEAR = 1_500
BEND2_BASE_CENTS = 600_000
BEND2_STEP_CENTS_PER_YEAR = 9_000
BEND_BASE_YEAR = 2024
SUBSTANTIAL_BASE_CENTS = 900_000
SUBSTANTIAL_STEP_CENTS_PER_YEAR = 22_500
COMPUTATION_YEARS = 35
WEP_FULL_EXEMPTION_YOC = 30
MAX_DRC_AGE_MONTHS = 840
MIN_CLAIM_AGE_MONTHS = 744
SURVIVOR_MIN_AGE_MONTHS = 720
SURVIVOR_FRA_MONTHS = 804

RATE_TIER_1 = Fraction(90, 100)
RATE_TIER_2 = Fraction(32, 100)
RATE_TIER_3 = Fraction(15, 100)
WEP_FLOOR_FACTOR = Fraction(40, 100)
WEP_STEP_PER_MISSING_YOC = Fraction(5, 100)
EARLY_RED_FIRST36 = Fraction(5, 900)
EARLY_RED_BEYOND36 = Fraction(5, 1200)
DRC_PER_MONTH = Fraction(1, 150)
SPOUSAL_RATE = Fraction(50, 100)
SPOUSAL_RED_FIRST36 = Fraction(25, 3600)
SPOUSAL_RED_BEYOND36 = Fraction(5, 1200)
GPO_FRACTION = Fraction(2, 3)
SURVIVOR_RED_PER_MONTH = Fraction(5, 1000)  # 0.005
FMAX_RATE_1 = Fraction(150, 100)
FMAX_RATE_2 = Fraction(272, 100)
FMAX_RATE_3 = Fraction(134, 100)
COLA_FACTOR = Fraction(1025, 1000)  # +2.5%


def awi_cents(year):
    return AWI_BASE_CENTS + AWI_STEP_CENTS_PER_YEAR * (year - AWI_BASE_YEAR)


def taxable_max_cents(year):
    return TAXABLE_MAX_BASE_CENTS + TAXABLE_MAX_STEP_CENTS_PER_YEAR * (year - AWI_BASE_YEAR)


def substantial_cents(year):
    return SUBSTANTIAL_BASE_CENTS + SUBSTANTIAL_STEP_CENTS_PER_YEAR * (year - AWI_BASE_YEAR)


def bend1_cents(eligibility_year):
    return BEND1_BASE_CENTS + BEND1_STEP_CENTS_PER_YEAR * (eligibility_year - BEND_BASE_YEAR)


def bend2_cents(eligibility_year):
    return BEND2_BASE_CENTS + BEND2_STEP_CENTS_PER_YEAR * (eligibility_year - BEND_BASE_YEAR)


def dime_floor(x):
    """Round a cent value DOWN to the next lower multiple of 10 cents."""
    return (floor(x) // 10) * 10


def round_half_up_cents(fr):
    """Round an exact rational to whole cents, halves rounding up."""
    return floor(fr + Fraction(1, 2))


# --- earnings indexation -----------------------------------------------------

def indexed_earnings_cents(worker, row):
    """posted earnings indexed to eligibility_year-2 wage level; face value
    for tax_year >= eligibility_year - 2."""
    ey = worker["eligibility_year"]
    posted = row["posted_earnings_cents"]
    ty = row["tax_year"]
    if ty < ey - 2:
        return round_half_up_cents(Fraction(posted * awi_cents(ey - 2), awi_cents(ty)))
    return posted


def earnings_rows_of(store, worker_id):
    return [r for r in store.earnings_years.values() if r["worker_id"] == worker_id]


def compute_aime_cents(store, worker):
    """35 highest indexed years; missing years are implicit zeros inside the
    fixed 35*12 divisor; monthly average floored to a whole dollar."""
    vals = sorted(
        (indexed_earnings_cents(worker, r) for r in earnings_rows_of(store, worker["id"])),
        reverse=True,
    )
    top_sum = sum(vals[:COMPUTATION_YEARS])
    return floor(Fraction(top_sum, COMPUTATION_YEARS * 12 * 100)) * 100


def years_of_substantial_coverage(store, worker):
    return sum(
        1
        for r in earnings_rows_of(store, worker["id"])
        if r["posted_earnings_cents"] >= substantial_cents(r["tax_year"])
    )


# --- PIA ---------------------------------------------------------------------

def pia_standard_cents(aime_cents, eligibility_year):
    b1 = bend1_cents(eligibility_year)
    b2 = bend2_cents(eligibility_year)
    total = (
        RATE_TIER_1 * min(aime_cents, b1)
        + RATE_TIER_2 * max(0, min(aime_cents, b2) - b1)
        + RATE_TIER_3 * max(0, aime_cents - b2)
    )
    return dime_floor(total)


def compute_pia_cents(store, worker, aime_cents):
    """Standard PIA, or the WEP-adjusted PIA when the worker draws a
    non-covered pension and has fewer than 30 substantial-coverage years."""
    ey = worker["eligibility_year"]
    standard = pia_standard_cents(aime_cents, ey)
    pension = worker["noncovered_pension_monthly_cents"]
    yoc = years_of_substantial_coverage(store, worker)
    if pension > 0 and yoc < WEP_FULL_EXEMPTION_YOC:
        tier1 = max(
            WEP_FLOOR_FACTOR,
            RATE_TIER_1 - WEP_STEP_PER_MISSING_YOC * (WEP_FULL_EXEMPTION_YOC - yoc),
        )
        b1 = bend1_cents(ey)
        b2 = bend2_cents(ey)
        wep_raw = dime_floor(
            tier1 * min(aime_cents, b1)
            + RATE_TIER_2 * max(0, min(aime_cents, b2) - b1)
            + RATE_TIER_3 * max(0, aime_cents - b2)
        )
        wep_reduction = standard - wep_raw
        guarantee_cap = pension // 2
        return standard - min(wep_reduction, guarantee_cap)
    return standard


# --- age adjustment ----------------------------------------------------------

def age_adjusted_monthly_cents(pia_cents, fra_months, claiming_age_months, drc_months):
    n_early = max(0, fra_months - claiming_age_months)
    if n_early > 0:
        factor = (
            1
            - min(n_early, 36) * EARLY_RED_FIRST36
            - max(0, n_early - 36) * EARLY_RED_BEYOND36
        )
    else:
        n_late = max(0, min(claiming_age_months, MAX_DRC_AGE_MONTHS) - fra_months) + drc_months
        factor = 1 + n_late * DRC_PER_MONTH
    return dime_floor(pia_cents * factor)


# --- auxiliary pieces --------------------------------------------------------

def spousal_base_cents(worker_pia_cents):
    return dime_floor(SPOUSAL_RATE * worker_pia_cents)


def spousal_reduced_cents(spousal_base, claimant_fra_months, claiming_age_months):
    s_early = max(0, claimant_fra_months - claiming_age_months)
    factor = (
        1
        - min(s_early, 36) * SPOUSAL_RED_FIRST36
        - max(0, s_early - 36) * SPOUSAL_RED_BEYOND36
    )
    return dime_floor(spousal_base * factor)


def survivor_benefit_cents(worker_pia_cents, claiming_age_months):
    s_early = max(0, SURVIVOR_FRA_MONTHS - claiming_age_months)
    factor = 1 - s_early * SURVIVOR_RED_PER_MONTH
    return dime_floor(worker_pia_cents * factor)


def gpo_offset_cents(claimant_worker):
    return dime_floor(GPO_FRACTION * claimant_worker["noncovered_pension_monthly_cents"])


def family_maximum_cents(worker_pia_cents, eligibility_year):
    b1 = bend1_cents(eligibility_year)
    b2 = bend2_cents(eligibility_year)
    total = (
        FMAX_RATE_1 * min(worker_pia_cents, b1)
        + FMAX_RATE_2 * max(0, min(worker_pia_cents, b2) - b1)
        + FMAX_RATE_3 * max(0, worker_pia_cents - b2)
    )
    return dime_floor(total)


def cola_adjusted_cents(monthly_benefit_cents):
    return dime_floor(monthly_benefit_cents * COLA_FACTOR)
