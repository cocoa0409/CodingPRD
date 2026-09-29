"""Domain constants and exact arithmetic helpers drawn from the PRD.

Every literal here is quoted from the PRD; the helpers reproduce the PRD's
pinned rounding modes (round-half-up for forage and money, floor for capacity,
ceiling for unauthorized use) so expected values in tests are computed the same
way the specification states them.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# --- Logical clock (PRD 2.5) ------------------------------------------------
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# --- Forage arithmetic (PRD 2.8, 3.4, 3.11) --------------------------------
GRAZING_DAYS_PER_AUM = 30
ANIMAL_UNIT_EQUIVALENT = {"CATTLE": Decimal("1.0"), "SHEEP": Decimal("0.2"), "HORSES": Decimal("1.25")}

# --- Base property qualification (PRD 3.2) ---------------------------------
QUALIFICATION_FACTOR = {"LAND": Decimal("1.0"), "LIVESTOCK": Decimal("0.75")}
PREFERENCE_PRIORITY = {"LAND": 1, "LIVESTOCK": 2}
DEFAULT_PREFERENCE_PRIORITY = 2

# --- Money (PRD 3.6, 3.11) -------------------------------------------------
GRAZING_FEE_CENTS_PER_AUM = 172
UNAUTHORIZED_USE_FEE_CENTS_PER_AUM = 2340
ADMIN_FEE_MID_THRESHOLD_CENTS = 50_000
ADMIN_FEE_HIGH_THRESHOLD_CENTS = 200_000
ADMIN_FEE_LOW_CENTS = 0
ADMIN_FEE_MID_CENTS = 2_500
ADMIN_FEE_HIGH_CENTS = 6_000
BILL_DUE_DAYS = 30
MIN_BILLABLE_FRACTION = Decimal("0.25")

# --- Trespass penalty (PRD 3.11) -------------------------------------------
WILLFULNESS_MULTIPLIER = {
    "NON_WILLFUL": Decimal("1.0"),
    "WILLFUL": Decimal("2.0"),
    "REPEATED_WILLFUL": Decimal("3.0"),
}
REPEAT_FACTOR_STEP = Decimal("0.25")
REPEAT_FACTOR_CAP = Decimal("2.0")

# --- Health assessment (PRD 3.7) -------------------------------------------
COMPOSITE_WEIGHT_UPLAND = Decimal("0.40")
COMPOSITE_WEIGHT_RIPARIAN = Decimal("0.35")
COMPOSITE_WEIGHT_WATER_QUALITY = Decimal("0.25")
DETERMINATION_MEETING_THRESHOLD = Decimal("70")
DETERMINATION_PROBLEMS_THRESHOLD = Decimal("50")
PER_STANDARD_REDUCTION_PCT = Decimal("0.10")
LIVESTOCK_CAUSATION_REDUCTION_PCT = Decimal("0.10")
RECOMMENDED_REDUCTION_CAP = Decimal("0.50")
TARGET_UTILIZATION_PCT = 50
MAX_ASSESSMENT_REMANDS = 2

# --- Closure orders and stocking adjustment (PRD 2.6, 3.8, 3.10) ----------
CLOSURE_BUFFER_DAYS = 7
MAX_PARTIAL_REDUCTION_PCT = Decimal("0.9")
TOTAL_CLOSURE_REDUCTION_PCT = Decimal("1.0")

# --- Ceilings (PRD 2.6) ----------------------------------------------------
MAX_CONSECUTIVE_NONUSE_YEARS = 3
MAX_APPEAL_REMANDS = 2
DEFAULT_REQUIRED_PASTURE_ROTATION_COUNT = 2
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --- Rounding helpers ------------------------------------------------------


def round_half_up(value, places: int = 2) -> Decimal:
    """Round half-up to `places` decimal places (PRD 2.8)."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_to_int(value) -> int:
    """Truncate downward to the next whole number (PRD 2.8)."""
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_FLOOR))


def ceil_to_int(value) -> int:
    """Raise to the next whole number, leaving whole values unchanged (PRD 2.8)."""
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING))


def forage_aums(head_count: int, livestock_kind: str, days: int) -> float:
    """head x AUE x days / 30, rounded half-up to 2 dp exactly once (PRD 3.4)."""
    raw = (
        Decimal(head_count)
        * ANIMAL_UNIT_EQUIVALENT[livestock_kind]
        * Decimal(days)
        / Decimal(GRAZING_DAYS_PER_AUM)
    )
    return float(round_half_up(raw, 2))


def admin_fee_cents(base_amount_cents: int) -> int:
    """Tiered administrative fee selected from base_amount_cents (PRD 3.6)."""
    if base_amount_cents < ADMIN_FEE_MID_THRESHOLD_CENTS:
        return ADMIN_FEE_LOW_CENTS
    if base_amount_cents < ADMIN_FEE_HIGH_THRESHOLD_CENTS:
        return ADMIN_FEE_MID_CENTS
    return ADMIN_FEE_HIGH_CENTS


def use_bill_base_cents(billed_aums) -> int:
    """billed_aums x 172 cents per AUM, rounded half-up to a whole cent (PRD 3.6)."""
    return int(round_half_up(Decimal(str(billed_aums)) * Decimal(GRAZING_FEE_CENTS_PER_AUM), 0))


def effective_capacity(total_permitted_aums: int, stocking_adjustment_pct) -> int:
    """total_permitted_aums x (1 - stocking_adjustment_pct), floored (PRD 2.9)."""
    return floor_to_int(
        Decimal(total_permitted_aums) * (Decimal("1") - Decimal(str(stocking_adjustment_pct)))
    )


def composite_score(upland: int, riparian: int, water_quality: int) -> float:
    """Weighted average of the three indicator scores, half-up to 2 dp (PRD 3.7)."""
    raw = (
        Decimal(upland) * COMPOSITE_WEIGHT_UPLAND
        + Decimal(riparian) * COMPOSITE_WEIGHT_RIPARIAN
        + Decimal(water_quality) * COMPOSITE_WEIGHT_WATER_QUALITY
    )
    return float(round_half_up(raw, 2))


def determination_for(score) -> str:
    """Band the composite score into a determination (PRD 3.7)."""
    value = Decimal(str(score))
    if value >= DETERMINATION_MEETING_THRESHOLD:
        return "MEETING"
    if value >= DETERMINATION_PROBLEMS_THRESHOLD:
        return "MEETING_WITH_PROBLEMS"
    return "NOT_MEETING"


def repeat_factor(prior_billed_incident_count: int) -> Decimal:
    """1.0 plus 0.25 per prior billed incident, capped at 2.0 (PRD 3.11)."""
    factor = Decimal("1.0") + REPEAT_FACTOR_STEP * Decimal(prior_billed_incident_count)
    return min(factor, REPEAT_FACTOR_CAP)


def trespass_penalty_cents(base_amount_cents: int, willfulness: str, prior_billed_incident_count: int) -> int:
    """base x (multiplier - 1.0) x repeat factor, half-up to a whole cent (PRD 3.11)."""
    raw = (
        Decimal(base_amount_cents)
        * (WILLFULNESS_MULTIPLIER[willfulness] - Decimal("1.0"))
        * repeat_factor(prior_billed_incident_count)
    )
    return int(round_half_up(raw, 0))
