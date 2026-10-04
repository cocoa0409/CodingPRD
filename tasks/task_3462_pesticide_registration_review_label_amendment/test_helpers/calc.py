"""Pure recomputation helpers mirroring the PRD's calculation rules.

Stage 2 tests use these to derive expected values instead of hand-encoding
arithmetic. All date math is on the logical clock (ISO-8601 instants);
all rounding is round-half-up per PRD §2.6.
"""
import math
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from .constants import (
    AMENDMENT_BASE_DAYS,
    BODY_WEIGHT_KG,
    BULLETIN_ADDER_DAYS,
    CONSUMPTION_G_DAY,
    DAYS_PER_OVERDUE_MONTH,
    DEPLETION_DAYS_PER_MONTH,
    FIXED_SALE_DAYS,
    FIXED_USE_DAYS,
    LATE_MONTHLY_RATE,
    LOC_DIETARY,
    LOC_ECOLOGICAL,
    LOC_OCCUPATIONAL,
    NEW_FOOD_USE_ADDER_DAYS,
    OCC_EXPOSURE_FACTOR,
    RENEWAL_PERIOD_DAYS,
    RUNOFF_FACTOR,
    RUP_ADDER_DAYS,
)


# ---------------------------------------------------------------------------
# Rounding discipline (PRD §2.6): round half up, decimal places pinned per
# quantity.
# ---------------------------------------------------------------------------
def round_half_up(value, places: int) -> float:
    """Round half-up to ``places`` decimal places; returns a float."""
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def round_half_up_int(value) -> int:
    """Round half-up to a whole integer (used for the late-penalty cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# ISO-8601 instant helpers (logical clock)
# ---------------------------------------------------------------------------
def parse_instant(iso_ts: str) -> datetime:
    """Parse an ISO-8601 UTC instant; accepts a trailing 'Z' or an offset."""
    text = iso_ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt: datetime) -> str:
    """Format a datetime as 'YYYY-MM-DDTHH:MM:SSZ' (whole-second, Z-suffixed)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(iso_ts: str, days: int) -> str:
    """Return the instant exactly ``days`` whole days after ``iso_ts``."""
    return format_instant(parse_instant(iso_ts) + timedelta(days=days))


def instants_equal(a: str, b: str) -> bool:
    """True when two ISO-8601 strings denote the same instant (format-tolerant)."""
    return parse_instant(a) == parse_instant(b)


def whole_days_between(earlier_iso: str, later_iso: str) -> int:
    """Whole days (floor) from the earlier to the later instant."""
    delta = parse_instant(later_iso) - parse_instant(earlier_iso)
    return delta.days if delta.total_seconds() >= 0 else -((-delta).days)


# ---------------------------------------------------------------------------
# Risk quotients (PRD §3.3)
# ---------------------------------------------------------------------------
def expected_dietary_exposure(
    tolerances: Iterable[Tuple[str, float]],
    tier: str,
    reference_dose_mg_kg_day: float,
    pct_crop_treated: Optional[float] = None,
    accepted_residue_means_ppm: Optional[Dict[str, float]] = None,
) -> Tuple[float, float]:
    """Recompute (dietary_exposure_mg_day, dietary_rq).

    ``tolerances``: (commodity_code, tolerance_ppm) pairs in PROPOSED or
    ESTABLISHED at assessment time — one pair per distinct commodity.
    ``accepted_residue_means_ppm``: for REFINED, the round-half-up-4dp mean of
    ACCEPTED RESIDUE_CHEMISTRY studies per commodity (omit commodities with no
    accepted study; those fall back to the SCREENING term).
    Rounding order pinned: per-commodity term to 4 dp, then sum, then 3 dp.
    """
    means = accepted_residue_means_ppm or {}
    terms: List[float] = []
    for commodity, tolerance_ppm in tolerances:
        consumption = CONSUMPTION_G_DAY[commodity]
        if tier == "REFINED" and commodity in means:
            mean_ppm = round_half_up(means[commodity], 4)
            term = round_half_up(mean_ppm * consumption * pct_crop_treated, 4)
        else:
            term = round_half_up(tolerance_ppm * consumption, 4)
        terms.append(term)
    exposure = round_half_up(sum(terms), 3) if terms else 0.0
    rq = round_half_up(exposure / (reference_dose_mg_kg_day * BODY_WEIGHT_KG), 3)
    return exposure, rq


def expected_residue_mean(residue_values_ppm: Iterable[float]) -> float:
    """Mean of ACCEPTED field-trial residues, itself rounded half-up to 4 dp."""
    values = list(residue_values_ppm)
    assert values, "mean requires at least one study"
    return round_half_up(sum(values) / len(values), 4)


def expected_occupational_rq(max_rate_lbs_acre: float,
                             reference_dose_mg_kg_day: float) -> float:
    """round_half_up(max_rate * 0.01 / (rfd * 70), 3); identical across tiers."""
    return round_half_up(
        max_rate_lbs_acre * OCC_EXPOSURE_FACTOR / (reference_dose_mg_kg_day * BODY_WEIGHT_KG), 3)


def expected_ecological_rq(sites: Iterable[Tuple[float, str]],
                           aquatic_lc50_ppm: float) -> float:
    """EEC = max(rate * RUNOFF_FACTOR[method]); quotient rounded to 3 dp.

    ``sites``: (max_application_rate_lbs_acre, application_method) pairs in
    PROPOSED or ACTIVE; empty -> 0.000.
    """
    eec = 0.0
    for rate, method in sites:
        eec = max(eec, rate * RUNOFF_FACTOR[method])
    return round_half_up(eec / aquatic_lc50_ppm, 3)


def expected_level_of_concern(dietary_rq: float, occupational_rq: float,
                              ecological_rq: float) -> bool:
    """Inclusive thresholds compared on the ROUNDED stored values."""
    return (dietary_rq >= LOC_DIETARY
            or occupational_rq >= LOC_OCCUPATIONAL
            or ecological_rq >= LOC_ECOLOGICAL)


# ---------------------------------------------------------------------------
# Amendment review timeline (PRD §3.5)
# ---------------------------------------------------------------------------
def expected_amendment_total_days(amendment_type: str,
                                  product_classification: str = "GENERAL_USE",
                                  has_tolerance_ppm: bool = False,
                                  bulletin_in_effect: bool = False,
                                  expedited: bool = False) -> int:
    """Base + adders, with METHOD_CHANGE expedited halving (ceil)."""
    total = AMENDMENT_BASE_DAYS[amendment_type]
    if product_classification == "RESTRICTED_USE":
        total += RUP_ADDER_DAYS
    if amendment_type == "NEW_USE" and has_tolerance_ppm:
        total += NEW_FOOD_USE_ADDER_DAYS
    if bulletin_in_effect:
        total += BULLETIN_ADDER_DAYS
    if expedited:
        total = math.ceil(total / 2)
    return total


def expected_amendment_review_due(submitted_at: str, amendment_type: str,
                                  product_classification: str = "GENERAL_USE",
                                  has_tolerance_ppm: bool = False,
                                  bulletin_in_effect: bool = False,
                                  expedited: bool = False) -> str:
    """submitted_at + total days, as an ISO instant string."""
    days = expected_amendment_total_days(
        amendment_type, product_classification, has_tolerance_ppm,
        bulletin_in_effect, expedited)
    return add_days(submitted_at, days)


def expected_priia_category(amendment_type: str, expedited: bool = False) -> str:
    """'<amendment_type>' or '<amendment_type>-EXPEDITED' when halving applied."""
    return f"{amendment_type}-EXPEDITED" if expedited else amendment_type


# ---------------------------------------------------------------------------
# Existing-stocks deadlines (PRD §3.8)
# ---------------------------------------------------------------------------
def expected_stocks_deadlines(effective_at: str, stocks_method: str,
                              authorized_units: Optional[int] = None,
                              depletion_rate_units_per_month: Optional[int] = None
                              ) -> Tuple[str, str]:
    """Return (allow_sale_until, allow_use_until) for the order's variant.

    FIXED: effective + 365 / + 730 days.
    DEPLETION: sale_days = ceil(units / rate * 30); use window = 2 x sale.
    """
    if stocks_method == "FIXED":
        return add_days(effective_at, FIXED_SALE_DAYS), add_days(effective_at, FIXED_USE_DAYS)
    assert stocks_method == "DEPLETION", f"unknown stocks_method {stocks_method}"
    assert authorized_units is not None and depletion_rate_units_per_month
    sale_days = math.ceil(authorized_units / depletion_rate_units_per_month
                          * DEPLETION_DAYS_PER_MONTH)
    return add_days(effective_at, sale_days), add_days(effective_at, 2 * sale_days)


# ---------------------------------------------------------------------------
# State-registration renewal fee (PRD §3.9) — evaluation order pinned:
# months overdue against the OLD renewal_due_at, penalty on the stamped
# subtotal, fee exact to the cent, and only then the anniversary moves.
# ---------------------------------------------------------------------------
def expected_months_overdue(renewal_due_at: str, clock_iso: str) -> int:
    """0 when clock <= renewal_due_at, else floor(days / 30) + 1."""
    if parse_instant(clock_iso) <= parse_instant(renewal_due_at):
        return 0
    return whole_days_between(renewal_due_at, clock_iso) // DAYS_PER_OVERDUE_MONTH + 1


def expected_renewal_fee_cents(annual_fee_cents: int, renewal_due_at: str,
                               clock_iso: str) -> int:
    """subtotal + round_half_up(subtotal * 0.10 * months_overdue, 0)."""
    months = expected_months_overdue(renewal_due_at, clock_iso)
    penalty = round_half_up_int(annual_fee_cents * LATE_MONTHLY_RATE * months)
    return annual_fee_cents + penalty


def expected_renewal_due_after_renewal(previous_renewal_due_at: str) -> str:
    """The anniversary moves exactly 365 days FROM ITS PREVIOUS VALUE."""
    return add_days(previous_renewal_due_at, RENEWAL_PERIOD_DAYS)


def expected_annual_fee_cents(state_code: str, product_classification: str) -> int:
    """State base fee plus the 10,000-cent surcharge for RESTRICTED_USE."""
    from .constants import STATE_BASE_FEE_CENTS, RUP_SURCHARGE_CENTS
    fee = STATE_BASE_FEE_CENTS[state_code]
    if product_classification == "RESTRICTED_USE":
        fee += RUP_SURCHARGE_CENTS
    return fee


# ---------------------------------------------------------------------------
# Registration-number minting (PRD §3.4)
# ---------------------------------------------------------------------------
def expected_epa_registration_number(previously_approved_count: int) -> str:
    """'EPA-RR-' + zero-padded 6-digit (previously APPROVED count + 1)."""
    from .constants import EPA_REGISTRATION_NUMBER_DIGITS, EPA_REGISTRATION_NUMBER_PREFIX
    seq = str(previously_approved_count + 1).zfill(EPA_REGISTRATION_NUMBER_DIGITS)
    return f"{EPA_REGISTRATION_NUMBER_PREFIX}{seq}"
