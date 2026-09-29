"""Calendar arithmetic and the nineteen calculation rules (PRD sections 2.8, 3.x).

Money is integer cents; rates are integer basis points.  Every fractional-cent
result is rounded half up to a whole cent, every percentile/percentage is
rounded half up to two decimal places, and exactly two quantities -- the
migration match rate and the patient-notice coverage -- are truncated toward
zero instead.
"""

import calendar
import decimal
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# Wide working precision so intermediate quotients never lose a digit that
# matters to the pinned half-up rounding points.
decimal.DefaultContext.prec = 60
decimal.getcontext().prec = 60

ONE = Decimal(1)
BPS = Decimal(10000)
CENT2 = Decimal("0.01")


def rhu(value):
    """Round half up to a whole cent (or whole wRVU)."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(ONE, rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to exactly two decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(CENT2, rounding=ROUND_HALF_UP)


def trunc_div(numerator, denominator):
    """Floor of a non-negative quotient (truncation toward zero)."""
    if denominator == 0:
        return 0
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.to_integral_value(rounding=decimal.ROUND_DOWN))


# ---------------------------------------------------------------------------
# Calendar arithmetic (PRD section 2.8): whole days, no time component.
# ---------------------------------------------------------------------------

def add_months(d, months):
    """Preserve day-of-month; fall back to the last day of the target month."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def add_years(d, years):
    """Preserve month and day; 29 February maps to 28 February in a non-leap year."""
    year = d.year + years
    last = calendar.monthrange(year, d.month)[1]
    return date(year, d.month, min(d.day, last))


def add_days(d, days):
    from datetime import timedelta
    return d + timedelta(days=days)


def day_diff(later, earlier):
    return (later - earlier).days


def last_day_of_month(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPINION_VALIDITY_MONTHS = 12

INTEGRATION_RESERVE_BPS = 350
SYNERGY_TIER_CEILINGS = (800000000, 1500000000, 2500000000)
SYNERGY_TIER_BPS = (0, 150, 275, 400)

FMV_SAFE_HARBOR_PERCENTILE = Decimal("90.00")
PERCENTILE_CEILING = Decimal("99")

MAX_PLAN_RETURNS = 2

COMMITTEE_MEETING_DAYS = (1, 15)

PAYER_LEAD_DAYS = {
    "COMMERCIAL": 90,
    "MANAGED_MEDICARE": 75,
    "MEDICARE": 60,
    "MEDICAID": 120,
}
RETRO_BILLING_WINDOW_DAYS = {
    "COMMERCIAL": 0,
    "MANAGED_MEDICARE": 0,
    "MEDICARE": 30,
    "MEDICAID": 0,
}

RECONCILE_MIN_BPS = 9950
MAX_MIGRATION_RETRIES = 2

DEFAULT_RETENTION_YEARS = 10
IMAGING_RETENTION_YEARS = 7
MINOR_RETENTION_AGE_YEARS = 21

PATIENT_NOTICE_LEAD_DAYS = 30
FULL_COVERAGE_BPS = 10000
PROVIDER_BASED_UPLIFT_BPS = 4000

TAIL_MIN_MONTHS = 60
TAIL_PREMIUM_RATE_BPS = {
    "PRIMARY_CARE": 15000,
    "CARDIOLOGY": 22500,
    "ORTHOPEDICS": 30000,
    "ONCOLOGY": 20000,
}

HR_COVERAGE_MIN_PCT = Decimal("80.00")

ANNUAL_HOURS = 2080
PTO_BUYOUT_RATE_BPS = 5000
ROLE_UPLIFT_BPS = {
    "MA": 400,
    "RN": 600,
    "FRONT_DESK": 250,
    "BILLER": 300,
    "PRACTICE_MANAGER": 800,
}
SYSTEM_PAY_SCALE_MIN_CENTS = {
    "MA": 4200000,
    "RN": 7600000,
    "FRONT_DESK": 3600000,
    "BILLER": 4400000,
    "PRACTICE_MANAGER": 9500000,
}

RETENTION_TIER_BPS = ((12, 200), (60, 500), (120, 800), (None, 1100))
CRITICAL_ROLES = ("RN", "BILLER", "PRACTICE_MANAGER")
CRITICAL_MULTIPLIER_BPS = 12500
NORMAL_MULTIPLIER_BPS = 10000
RETENTION_FLOOR_CENTS = 100000
RETENTION_CAP_CENTS = 1500000

SURVEY_TOTAL_CASH_COMP = {
    "PRIMARY_CARE": (22000000, 26500000, 31000000, 36000000),
    "CARDIOLOGY": (45000000, 55000000, 68000000, 82000000),
    "ORTHOPEDICS": (50000000, 62000000, 76000000, 92000000),
    "ONCOLOGY": (40000000, 49000000, 60000000, 72000000),
}
SURVEY_COMP_PER_WRVU = {
    "PRIMARY_CARE": (4200, 5200, 6300, 7600),
    "CARDIOLOGY": (5600, 6900, 8300, 9800),
    "ORTHOPEDICS": (6100, 7400, 9000, 10800),
    "ONCOLOGY": (5200, 6400, 7800, 9300),
}

TASK_DOMAIN = {
    "HR_STAFFING_PLAN": "HR",
    "PAYER_CREDENTIALING": "REVENUE_CYCLE",
    "IT_DATA_MIGRATION": "IT",
    "REVENUE_CYCLE_GO_LIVE": "REVENUE_CYCLE",
    "COMPLIANCE_TRAINING": "COMPLIANCE",
    "PATIENT_NOTIFICATION": "CLINICAL",
}


# ---------------------------------------------------------------------------
# 1. fmv_concluded_value (PRD section 3.2)
# ---------------------------------------------------------------------------

def fmv_concluded_value(opinion_type, method, normalized_ebitda_cents,
                        projection_years, ebitda_growth_bps,
                        discount_rate_bps, terminal_growth_bps,
                        market_multiple_bps):
    if opinion_type == "COMMERCIAL_REASONABLENESS":
        return 0
    if method == "MARKET_APPROACH":
        return rhu(Decimal(normalized_ebitda_cents) * Decimal(market_multiple_bps) / BPS)
    # INCOME_APPROACH: discounted cash flow plus a Gordon-growth terminal value,
    # with every projected year and the terminal value rounded independently.
    e0 = Decimal(normalized_ebitda_cents)
    g = Decimal(ebitda_growth_bps) / BPS
    r = Decimal(discount_rate_bps) / BPS
    tg = Decimal(terminal_growth_bps) / BPS
    horizon = int(projection_years)
    explicit_pv = 0
    for year in range(1, horizon + 1):
        projected = rhu(e0 * (ONE + g) ** year)
        explicit_pv += rhu(Decimal(projected) / (ONE + r) ** year)
    final_year = rhu(e0 * (ONE + g) ** horizon)
    terminal = rhu(Decimal(final_year) * (ONE + tg) / (r - tg))
    discounted_terminal = rhu(Decimal(terminal) / (ONE + r) ** horizon)
    return explicit_pv + discounted_terminal


def opinion_expires_on(effective_on):
    return add_months(effective_on, OPINION_VALIDITY_MONTHS)


# ---------------------------------------------------------------------------
# 2. deal_net_consideration (PRD section 3.3)
# ---------------------------------------------------------------------------

def malpractice_tail_premium(tail_coverage_required, specialty,
                             annual_malpractice_premium_cents,
                             tail_coverage_months):
    """3. malpractice_tail_premium -- rounded half up exactly once at the end."""
    if not tail_coverage_required:
        return 0
    rate = TAIL_PREMIUM_RATE_BPS[specialty]
    return rhu(
        Decimal(annual_malpractice_premium_cents) * Decimal(rate) / BPS
        * Decimal(tail_coverage_months) / Decimal(60)
    )


def synergy_tier_bps(gross_consideration_cents):
    """The tier is keyed on the gross figure and is never re-derived from the net."""
    for index, ceiling in enumerate(SYNERGY_TIER_CEILINGS):
        if gross_consideration_cents < ceiling:
            return SYNERGY_TIER_BPS[index]
    return SYNERGY_TIER_BPS[-1]


def deal_net_consideration(purchase_price_cents, tail_premium_cents,
                           escrow_committed_cents):
    integration_reserve = rhu(
        Decimal(purchase_price_cents) * Decimal(INTEGRATION_RESERVE_BPS) / BPS
    )
    gross = (purchase_price_cents + integration_reserve
             + tail_premium_cents + escrow_committed_cents)
    credit_bps = synergy_tier_bps(gross)
    credit = rhu(Decimal(gross) * Decimal(credit_bps) / BPS)
    return {
        "integration_reserve_cents": integration_reserve,
        "gross_consideration_cents": gross,
        "synergy_credit_bps": credit_bps,
        "synergy_credit_cents": credit,
        "net_consideration_cents": gross - credit,
    }


# ---------------------------------------------------------------------------
# 4. projected_total_cash_comp / comp_per_wrvu (PRD section 3.4)
# ---------------------------------------------------------------------------

def projected_total_cash_comp(model_type, base_salary_cents,
                              conversion_factor_cents_per_wrvu,
                              threshold_wrvu, projected_annual_wrvu):
    if model_type == "STRAIGHT_SALARY":
        return base_salary_cents
    if model_type == "WRVU_PRODUCTIVITY":
        return rhu(Decimal(conversion_factor_cents_per_wrvu)
                   * Decimal(projected_annual_wrvu))
    incentive_volume = projected_annual_wrvu - threshold_wrvu
    if incentive_volume < 0:
        incentive_volume = 0
    return base_salary_cents + rhu(
        Decimal(conversion_factor_cents_per_wrvu) * Decimal(incentive_volume)
    )


def comp_per_wrvu(total_cash_comp_cents, wrvu):
    if wrvu == 0:
        return 0
    return rhu(Decimal(total_cash_comp_cents) / Decimal(wrvu))


def benchmark_basis_for(model_type):
    return "COMP_PER_WRVU" if model_type == "WRVU_PRODUCTIVITY" else "TOTAL_CASH_COMP"


# ---------------------------------------------------------------------------
# 5. compensation_benchmark_percentile (PRD section 3.4)
# ---------------------------------------------------------------------------

def survey_quartiles(benchmark_basis, specialty):
    table = (SURVEY_COMP_PER_WRVU if benchmark_basis == "COMP_PER_WRVU"
             else SURVEY_TOTAL_CASH_COMP)
    return table[specialty]


def compensation_benchmark_percentile(value, benchmark_basis, specialty):
    p25, p50, p75, p90 = survey_quartiles(benchmark_basis, specialty)
    v = Decimal(value)
    if v <= p25:
        pct = Decimal(25) * v / Decimal(p25)
    elif v <= p50:
        pct = Decimal(25) + Decimal(25) * (v - p25) / Decimal(p50 - p25)
    elif v <= p75:
        pct = Decimal(50) + Decimal(25) * (v - p50) / Decimal(p75 - p50)
    elif v <= p90:
        pct = Decimal(75) + Decimal(15) * (v - p75) / Decimal(p90 - p75)
    else:
        pct = Decimal(90) + Decimal(9) * (v - p90) / Decimal(p90)
        if pct > PERCENTILE_CEILING:
            pct = PERCENTILE_CEILING
    return rhu2(pct)


# ---------------------------------------------------------------------------
# 6. staff_offer_wage_harmonization (PRD section 3.8)
# ---------------------------------------------------------------------------

def staff_offer_wage_harmonization(role_code, legacy_annual_wage_cents,
                                   legacy_pto_hours):
    """Both components are rounded independently before the sum; the pay-scale
    floor is applied last, and a sum landing exactly on the floor is not
    displaced."""
    uplift = rhu(Decimal(legacy_annual_wage_cents)
                 * Decimal(ROLE_UPLIFT_BPS[role_code]) / BPS)
    hourly = Decimal(legacy_annual_wage_cents) / Decimal(ANNUAL_HOURS)
    pto = rhu(Decimal(legacy_pto_hours) * hourly
              * Decimal(PTO_BUYOUT_RATE_BPS) / BPS)
    harmonized = legacy_annual_wage_cents + uplift + pto
    floor = SYSTEM_PAY_SCALE_MIN_CENTS[role_code]
    if harmonized < floor:
        offered = floor
        floor_applied = True
    else:
        offered = harmonized
        floor_applied = False
    return {
        "uplift_component_cents": uplift,
        "pto_component_cents": pto,
        "offered_annual_wage_cents": offered,
        "wage_floor_applied": floor_applied,
    }


# ---------------------------------------------------------------------------
# 7. retention_bonus_award (PRD section 3.8)
# ---------------------------------------------------------------------------

def retention_tier_bps(credited_service_months):
    for ceiling, bps in RETENTION_TIER_BPS:
        if ceiling is None or credited_service_months < ceiling:
            return bps
    return RETENTION_TIER_BPS[-1][1]


def retention_bonus_award(role_code, offered_annual_wage_cents,
                          credited_service_months):
    tier = retention_tier_bps(credited_service_months)
    raw = rhu(Decimal(offered_annual_wage_cents) * Decimal(tier) / BPS)
    multiplier = (CRITICAL_MULTIPLIER_BPS if role_code in CRITICAL_ROLES
                  else NORMAL_MULTIPLIER_BPS)
    adjusted = rhu(Decimal(raw) * Decimal(multiplier) / BPS)
    # Clamp in a fixed order: floor first, then cap.
    if adjusted < RETENTION_FLOOR_CENTS:
        adjusted = RETENTION_FLOOR_CENTS
    if adjusted > RETENTION_CAP_CENTS:
        adjusted = RETENTION_CAP_CENTS
    return adjusted


# ---------------------------------------------------------------------------
# 8. hr_staffing_coverage (PRD section 3.8)
# ---------------------------------------------------------------------------

def hr_staffing_coverage(seated_count, required_staff_headcount):
    if required_staff_headcount == 0:
        return rhu2(Decimal(0))
    return rhu2(Decimal(seated_count) * Decimal(100)
                / Decimal(required_staff_headcount))


# ---------------------------------------------------------------------------
# 9. comp_true_up (PRD section 3.11)
# ---------------------------------------------------------------------------

def comp_true_up(plan, actual_ytd_wrvu, months_elapsed):
    model = plan["model_type"]
    base = plan["base_salary_cents"]
    factor = plan["conversion_factor_cents_per_wrvu"]
    threshold = plan["threshold_wrvu"]

    prorated_threshold = rhu(Decimal(threshold) * Decimal(months_elapsed)
                             / Decimal(12))
    if model == "STRAIGHT_SALARY":
        earned = rhu(Decimal(base) * Decimal(months_elapsed) / Decimal(12))
    elif model == "WRVU_PRODUCTIVITY":
        earned = rhu(Decimal(factor) * Decimal(actual_ytd_wrvu))
    else:
        excess = actual_ytd_wrvu - prorated_threshold
        if excess < 0:
            excess = 0
        earned = (rhu(Decimal(base) * Decimal(months_elapsed) / Decimal(12))
                  + rhu(Decimal(factor) * Decimal(excess)))
    paid_to_date = rhu(Decimal(plan["projected_total_cash_comp_cents"])
                       * Decimal(months_elapsed) / Decimal(12))
    true_up = earned - paid_to_date

    annualized_wrvu = rhu(Decimal(actual_ytd_wrvu) * Decimal(12)
                          / Decimal(months_elapsed))
    annualized_total = projected_total_cash_comp(
        model, base, factor, threshold, annualized_wrvu)
    annualized_per_wrvu = comp_per_wrvu(annualized_total, annualized_wrvu)
    return {
        "prorated_threshold_wrvu": prorated_threshold,
        "earned_cents": earned,
        "paid_to_date_cents": paid_to_date,
        "comp_true_up_cents": true_up,
        "annualized_wrvu": annualized_wrvu,
        "annualized_total_cash_comp_cents": annualized_total,
        "annualized_comp_per_wrvu_cents": annualized_per_wrvu,
    }


# ---------------------------------------------------------------------------
# 10. compensation_plan_revision_limit (PRD section 3.4)
# ---------------------------------------------------------------------------

def plan_return_outcome(returned_count):
    """Two returns are allowed; the counter increments on both outcomes."""
    if returned_count < MAX_PLAN_RETURNS:
        return "DRAFT"
    return "WITHDRAWN"


# ---------------------------------------------------------------------------
# 11/12. credentialing_committee_cycle_key, credentialing_projected_effective_date
# (PRD section 3.6)
# ---------------------------------------------------------------------------

def next_committee_meeting(d):
    """Earliest first-or-fifteenth of a month on or after d (lower-inclusive)."""
    if d.day <= 1:
        return date(d.year, d.month, 1)
    if d.day <= 15:
        return date(d.year, d.month, 15)
    return add_months(date(d.year, d.month, 1), 1)


def committee_cycle_key(submitted_on):
    return next_committee_meeting(submitted_on)


def credentialing_lead_days(payer_type):
    return PAYER_LEAD_DAYS[payer_type]


def credentialing_projected_effective_date(submitted_on, lead_days):
    return next_committee_meeting(add_days(submitted_on, lead_days))


def retro_billing_allowed(payer_type):
    return RETRO_BILLING_WINDOW_DAYS[payer_type] > 0


# ---------------------------------------------------------------------------
# 13. payer_contract_interval_overlap (PRD section 3.6)
# ---------------------------------------------------------------------------

def intervals_overlap(new_effective, new_terminates, peer_effective,
                      peer_terminates):
    """Closed intervals on both endpoints: touching terms do collide."""
    return new_effective <= peer_terminates and peer_effective <= new_terminates


# ---------------------------------------------------------------------------
# 14. ehr_reconciliation_match_rate (PRD section 3.7)
# ---------------------------------------------------------------------------

def ehr_match_rate_bps(validated_count, record_count):
    return trunc_div(validated_count * 10000, record_count)


# ---------------------------------------------------------------------------
# 15. legacy_retention_years (PRD section 3.7)
# ---------------------------------------------------------------------------

def legacy_retention_years(chart_type, contains_minor_records,
                           youngest_patient_age_years):
    base = (IMAGING_RETENTION_YEARS if chart_type == "IMAGING"
            else DEFAULT_RETENTION_YEARS)
    if not contains_minor_records:
        return base
    minor_years = MINOR_RETENTION_AGE_YEARS - int(youngest_patient_age_years)
    return base if base >= minor_years else minor_years


def legacy_purge_eligible_on(last_encounter_on, retention_years):
    return add_years(last_encounter_on, retention_years)


# ---------------------------------------------------------------------------
# 16. patient_notice_coverage (PRD section 3.9)
# ---------------------------------------------------------------------------

def patient_notice_coverage_bps(notified_patient_count, required_notice_count):
    return trunc_div(notified_patient_count * 10000, required_notice_count)


def notice_lead_days(notices_issued_on, effective_on):
    if notices_issued_on is None:
        return None
    return day_diff(effective_on, notices_issued_on)


def provider_based_uplift_bps(conversion_type):
    return (PROVIDER_BASED_UPLIFT_BPS
            if conversion_type == "PROVIDER_BASED_DEPARTMENT" else 0)


# ---------------------------------------------------------------------------
# 17. acquisition_readiness_posture (PRD section 3.10)
# ---------------------------------------------------------------------------

def acquisition_readiness_posture(tasks):
    blocking = [t for t in tasks if t.get("is_blocking")]
    if not blocking:
        return "BLOCKED"
    for task in blocking:
        if task["status"] == "FAILED":
            return "BLOCKED"
    for task in blocking:
        if task["status"] in ("OPEN", "IN_PROGRESS"):
            return "AT_RISK"
    return "READY"
