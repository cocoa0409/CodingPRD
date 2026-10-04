"""Calculation rules (scaffold §1.3) — pure functions and pinned constants."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from clock import add_months, month_diff, month_str, parse_date, parse_month

# --- pinned constants -------------------------------------------------------
PART_B_LEP_PCT_PER_PERIOD = 10      # 10% per full 12-month period uncovered
PERIOD_MONTHS = 12                  # months per full penalty period
PART_D_LEP_PCT_PER_MONTH = 1        # 1% of national base per uncovered month
PAST_DUE_TERMINATION_THRESHOLD = 3  # >= 3 PAST_DUE invoices -> termination
LARGE_EMPLOYER_MIN_SIZE = 20        # employer_size >= 20 counts as large
IRMAA_TIER_COUNT = 6                # exactly 6 brackets, tiers 0..5

PARTS_BILLABLE = ("PART_B", "PART_D")


# --- rounding ----------------------------------------------------------------
def round_half_up(x) -> int:
    """Round to the nearest whole cent, halves up."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_dime(x) -> int:
    """Round to the nearest 10 cents, half-up: 448.5 -> 450, 241.5 -> 240."""
    return int((Decimal(str(x)) / Decimal(10)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP) * 10)


# --- attainment / IEP --------------------------------------------------------
def calc_attainment_month(date_of_birth: str):
    """Returns (attainment_month, iep_start_month, iep_end_month) strings.

    attainment = month the person turns 65, EXCEPT birth day == 1 -> the
    month BEFORE the 65th-birthday month. IEP = [attainment-3, attainment+3].
    """
    d = parse_date(date_of_birth)
    y65 = d.year + 65
    if d.day == 1:
        attainment = add_months((y65, d.month), -1)
    else:
        attainment = (y65, d.month)
    return (
        month_str(attainment),
        month_str(add_months(attainment, -3)),
        month_str(add_months(attainment, 3)),
    )


# --- coverage effective month -------------------------------------------------
def calc_coverage_effective_month(window: str, attainment_month: str, clock_m):
    """IEP delay rules; SEP/GEP -> month after enrollment month."""
    if window == "IEP":
        t = parse_month(attainment_month)
        delta = month_diff(clock_m, t)
        if delta < 0:
            return t
        if delta == 0:
            return add_months(clock_m, 1)
        if delta == 1:
            return add_months(clock_m, 2)
        return add_months(clock_m, 3)  # delta in {2, 3} (window is open)
    # SEP and GEP: effective the month after the enrollment month
    return add_months(clock_m, 1)


def calc_sep_window(employment_end_month: str, coverage_end_month: str):
    """anchor = whichever ended FIRST; SEP = [anchor+1, anchor+8] inclusive."""
    anchor = min(parse_month(employment_end_month), parse_month(coverage_end_month))
    return add_months(anchor, 1), add_months(anchor, 8)


# --- late enrollment penalties -------------------------------------------------
def calc_part_b_periods(gap_months: int):
    full_periods = gap_months // PERIOD_MONTHS
    return full_periods, PART_B_LEP_PCT_PER_PERIOD * full_periods


def calc_part_b_lep_cents(penalty_pct: int, part_b_standard_cents: int) -> int:
    return round_half_up(Decimal(part_b_standard_cents) * penalty_pct / 100)


def calc_part_d_lep_cents(gap_months: int, part_d_national_base_cents: int) -> int:
    # PINNED aggregation: multiply first, round ONCE at the end, to the dime.
    return round_dime(Decimal(gap_months) * PART_D_LEP_PCT_PER_MONTH
                      * Decimal(part_d_national_base_cents) / 100)


# --- IRMAA ---------------------------------------------------------------------
def calc_irmaa_tier(brackets, filing_status: str, magi_cents: int) -> int:
    """Highest tier whose floor <= MAGI; lower bound INCLUSIVE."""
    floor_key = ("single_floor_cents" if filing_status == "SINGLE"
                 else "joint_floor_cents")
    tier = 0
    for b in sorted(brackets, key=lambda x: x["tier"]):
        if b[floor_key] <= magi_cents:
            tier = b["tier"]
    return tier


def bracket_for_tier(brackets, tier: int):
    for b in brackets:
        if b["tier"] == tier:
            return b
    return None
