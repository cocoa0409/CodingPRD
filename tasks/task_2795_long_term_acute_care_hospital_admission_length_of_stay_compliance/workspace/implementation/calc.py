"""Domain arithmetic: day counting, half-up rounding, and every calculation in PRD 3."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---- constants (PRD 2.5, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8) ------------------- #
BASE_REFERRAL_THRESHOLD_PCT = Decimal("25.00")
EXPANDED_REFERRAL_THRESHOLD_PCT = Decimal("50.00")
WARNING_MARGIN_PCT = Decimal("5.00")
MIN_ADMISSIONS_FOR_MONITORING = 4

SSO_ALOS_FRACTION = Decimal("0.8333333333333334")
SSO_IPPS_PER_DIEM_FACTOR = Decimal("1.20")

FIXED_LOSS_AMOUNT_CENTS = 3000000
OUTLIER_MARGINAL_COST_FACTOR = Decimal("0.80")

VENT_HOURS_SITE_NEUTRAL_MIN = Decimal("96")
ICU_DAYS_SITE_NEUTRAL_MIN = 3

PROGRESSION_STEPS_REQUIRED = 2
MIN_SBT_ATTEMPTS_FOR_VENT_DEPENDENT = 3

MAX_INTERRUPTIONS_PER_STAY = 3
INTERRUPTION_BUFFER_HOURS = 24
INTERRUPTION_WINDOW_DAYS = {"ACUTE_CARE": 9, "IRF": 27, "SNF": 27, "HOME": 3}
RECOMBINATION_WINDOW_DAYS = 3
QUERY_RESPONSE_WINDOW_HOURS = 72

MISSING_DISCIPLINE_WEIGHT = Decimal("8")
WEANING_GAP_WEIGHT = Decimal("15")
SSO_WEIGHT = Decimal("20")
SITE_NEUTRAL_WEIGHT = Decimal("10")
LOS_EXCESS_WEIGHT = Decimal("0.5")
ANSWERED_QUERY_CREDIT = Decimal("12")
HIGH_BAND_MIN = 70
MODERATE_BAND_MIN = 40

REQUIRED_DISCIPLINES = ("PHYSICIAN", "NURSING", "RESPIRATORY_THERAPY", "CASE_MANAGEMENT")


# ---- primitives ----------------------------------------------------------- #

def day_count(start, end):
    """Whole-day count between two instants: difference of their UTC calendar dates.

    The later day is not itself counted, so a discharge on the admission date is 0.
    """
    if start is None or end is None:
        return 0
    return (end.date() - start.date()).days


def round_half_up(value, places=0):
    """Nearest unit at `places` decimals, ties away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a monetary expression to whole cents, half-up, and return an int."""
    return int(round_half_up(value, 0))


def pct(value):
    """A percentage carried to exactly two decimals, half-up."""
    return round_half_up(value, 2)


def floor_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def hours(value):
    """Ventilator hours are decimal numbers carried to one decimal place."""
    return round_half_up(value, 1)


# ---- covered length of stay (PRD 3.6) ------------------------------------- #

def sso_threshold_days(alos_days):
    """Five-sixths of the DRG's alos_days, rounded down and never to nearest."""
    return floor_int(SSO_ALOS_FRACTION * Decimal(alos_days))


def covered_los_days(stay):
    segment_start = stay.get("resumed_at") or stay.get("admitted_at")
    segment_days = day_count(segment_start, stay.get("discharged_at"))
    return stay.get("carried_los_days", 0) + segment_days - stay.get("interruption_days_total", 0)


# ---- high-cost outlier add-on (PRD 3.7 step four) ------------------------- #

def high_cost_outlier(base_cents, estimated_cost_cents):
    """Pinned evaluation order: the add-on never re-enters its own threshold."""
    cost = estimated_cost_cents if estimated_cost_cents is not None else 0
    threshold_cents = base_cents + FIXED_LOSS_AMOUNT_CENTS
    excess_cents = cost - threshold_cents
    if excess_cents <= 0:
        return 0
    return cents(OUTLIER_MARGINAL_COST_FACTOR * Decimal(excess_cents))


# ---- dual-variant pricing (PRD 3.7) -------------------------------------- #

def full_standard_amount_cents(drg):
    return cents(Decimal(drg["standard_federal_rate_cents"]) * drg["relative_weight"])


def standard_base_cents(drg, full_amount, los, sso_applied):
    """PRD 3.7 step two."""
    if not sso_applied:
        return full_amount
    los_dec = Decimal(los if los is not None else 0)
    per_diem_component = cents(
        Decimal(full_amount) / Decimal(drg["alos_days"]) * los_dec
    )
    candidate_a = min(full_amount, per_diem_component)
    candidate_b = cents(
        Decimal(drg["ipps_comparable_per_diem_cents"]) * los_dec * SSO_IPPS_PER_DIEM_FACTOR
    )
    candidate_c = drg["ipps_comparable_full_cents"]
    return min(candidate_a, candidate_b, candidate_c)


def site_neutral_base_cents(drg, estimated_cost_cents):
    """PRD 3.7 step three."""
    cost = estimated_cost_cents if estimated_cost_cents is not None else 0
    return min(drg["ipps_comparable_full_cents"], cost)


def discharge_payment_pct(base_payment_cents, full_amount):
    """PRD 3.7: base payment (excluding the outlier add-on) over the full DRG amount."""
    if full_amount == 0:
        return pct(Decimal(0))
    return pct(Decimal(base_payment_cents) / Decimal(full_amount) * Decimal(100))


# ---- referral-mix share (PRD 3.3) ---------------------------------------- #

def hospital_threshold_pct(hospital):
    if hospital.get("is_colocated") or hospital.get("hospital_type") == "CRITICAL_ACCESS":
        return EXPANDED_REFERRAL_THRESHOLD_PCT
    return BASE_REFERRAL_THRESHOLD_PCT


def share_pct(admissions_in_period, total_admissions):
    if total_admissions == 0:
        return pct(Decimal(0))
    return pct(Decimal(admissions_in_period) / Decimal(total_admissions) * Decimal(100))


def monitoring_state(share, threshold, total_admissions):
    if total_admissions < MIN_ADMISSIONS_FOR_MONITORING:
        return "COMPLIANT"
    if share > threshold:
        return "BREACHED"
    if share > (threshold - WARNING_MARGIN_PCT):
        return "WARNING"
    return "COMPLIANT"


# ---- denial-risk score (PRD 3.8) ----------------------------------------- #

def clamp_score(raw):
    value = int(round_half_up(raw, 0))
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value


def risk_band(effective_score):
    if effective_score >= HIGH_BAND_MIN:
        return "HIGH"
    if effective_score >= MODERATE_BAND_MIN:
        return "MODERATE"
    return "LOW"
