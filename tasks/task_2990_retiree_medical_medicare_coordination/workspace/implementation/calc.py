"""Every named calculation in the programme (PRD 2.6, 2.9, 3.x).

All arithmetic is integer arithmetic in cents or basis points, and every
division truncates toward zero at the exact step the rule names -- never later.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from validate import parse_date_string

# --- fixed benchmarks and thresholds ----------------------------------------
STANDARD_PART_D_GROSS_VALUE_BPS = 10000
STANDARD_PART_D_NET_VALUE_BPS = 7450

ADMIN_FEE_BPS = 350
PREMIUM_DUE_DAYS = 30
BPS_DENOMINATOR = 10000

SUBSIDY_BPS_BY_GROUP = {
    "GRANDFATHERED_A": 8000,
    "TRANSITION_B": 6000,
    "STANDARD_C": 4000,
}
LONG_SERVICE_YEARS = 25
LONG_SERVICE_BUMP_BPS = 1000
MAX_SUBSIDY_BPS = 10000

DENTAL_VISION_REIMBURSEMENT_BPS = 5000
QUALIFIED_MEDICAL_PER_CLAIM_CAP_CENTS = 50000

LIFE_EVENT_WINDOW_DAYS = 31
ESRD_COORDINATION_MONTHS = 30
WORKING_AGED_EMPLOYER_SIZE = 20
DISABILITY_EMPLOYER_SIZE = 100
LAPSE_THRESHOLD_PERIODS = 3
SECONDS_PER_DAY = 86400

GRANDFATHER_CUTOFF_A = date(1993, 1, 1)
GRANDFATHER_CUTOFF_B = date(2005, 1, 1)

RULE_SET_BY_GROUP = {
    "GRANDFATHERED_A": "RULE_OF_75_GRANDFATHERED",
    "TRANSITION_B": "AGE_60_SERVICE_15",
    "STANDARD_C": "AGE_65_SERVICE_10",
}

FULL_ELIGIBILITY_YEARS_BY_GROUP = {
    "GRANDFATHERED_A": 15,
    "TRANSITION_B": 20,
    "STANDARD_C": 25,
}
POST_ELIGIBILITY_SERVICE_YEARS = 5

MEDICARE_ENROLLED = "MEDICARE_ENROLLED"

COVERAGE_CLASS_BY_MEDICARE_POSTURE = {
    "MEDICARE_ENROLLED": ("MEDICARE_GROUP_WRAP", "INDIVIDUAL_EXCHANGE_HRA"),
    "PRE_MEDICARE": ("PRE_MEDICARE_GROUP", "INDIVIDUAL_EXCHANGE_HRA"),
    "MEDICARE_ELIGIBLE_NOT_ENROLLED": ("PRE_MEDICARE_GROUP", "INDIVIDUAL_EXCHANGE_HRA"),
    "MEDICARE_WAIVED": ("PRE_MEDICARE_GROUP", "INDIVIDUAL_EXCHANGE_HRA"),
}

ACTIVE_COVERAGE_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED")


# --- date and instant helpers -----------------------------------------------
def midnight(day):
    """A YYYY-MM-DD calendar date taken at midnight UTC."""
    if isinstance(day, str):
        day = parse_date_string(day)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    return parse_date_string(value)


def completed_age_years(birth_date, retirement_date):
    """Whole completed years: year difference, less one when the later
    month-and-day falls strictly before the earlier month-and-day."""
    b = as_date(birth_date)
    r = as_date(retirement_date)
    years = r.year - b.year
    if (r.month, r.day) < (b.month, b.day):
        years -= 1
    return years


def service_years(credited_service_months):
    return credited_service_months // 12


def whole_months_between(earlier, later):
    """Exact integer month arithmetic used by the renal-disease branches."""
    e = as_date(earlier)
    l = as_date(later)
    months = (l.year - e.year) * 12 + (l.month - e.month)
    if l.day < e.day:
        months -= 1
    return months


def whole_days_between(earlier_instant, later_instant):
    """Truncated to whole days of 86400 seconds each."""
    delta = later_instant - earlier_instant
    return int(delta.total_seconds() // SECONDS_PER_DAY)


def first_day_of_next_month(day):
    d = as_date(day)
    if d.month == 12:
        return datetime(d.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(d.year, d.month + 1, 1, tzinfo=timezone.utc)


def plus_days(instant, days):
    return instant + timedelta(days=days)


def plus_year_minus_day(instant):
    """The plan-year expense window's inclusive upper bound: one year after the
    coverage start, minus one day."""
    try:
        shifted = instant.replace(year=instant.year + 1)
    except ValueError:  # 29 February
        shifted = instant.replace(year=instant.year + 1, day=28)
    return shifted - timedelta(days=1)


# --- grandfather cohort and eligibility rule sets ----------------------------
def grandfather_group(hire_date):
    h = as_date(hire_date)
    if h < GRANDFATHER_CUTOFF_A:
        return "GRANDFATHERED_A"
    if h < GRANDFATHER_CUTOFF_B:
        return "TRANSITION_B"
    return "STANDARD_C"


def rule_set_code(group):
    return RULE_SET_BY_GROUP[group]


def evaluate_eligibility(group, age_years, years_of_service):
    """Every threshold is inclusive."""
    points = age_years + years_of_service
    if group == "GRANDFATHERED_A":
        ok = points >= 75 and age_years >= 55 and years_of_service >= 10
    elif group == "TRANSITION_B":
        ok = age_years >= 60 and years_of_service >= 15
    else:
        ok = age_years >= 65 and years_of_service >= 10
    return "ELIGIBLE" if ok else "INELIGIBLE"


def eligibility_points(retiree):
    return (completed_age_years(retiree["birth_date"], retiree["retirement_date"])
            + service_years(retiree["credited_service_months"]))


# --- Medicare secondary payer determination (eight ordered branches) ---------
def msp_determination(retiree, clock):
    if retiree["medicare_status"] != MEDICARE_ENROLLED:
        return "GROUP_PRIMARY", "NO_OTHER_COVERAGE"

    esrd_date = retiree.get("esrd_entitlement_date")
    if retiree.get("esrd_flag") and esrd_date is not None:
        if whole_months_between(esrd_date, clock) < ESRD_COORDINATION_MONTHS:
            return "GROUP_PRIMARY", "ESRD_WITHIN_COORDINATION"
        return "MEDICARE_PRIMARY", "ESRD_AFTER_COORDINATION"

    size = retiree.get("other_group_coverage_employer_size") or 0
    if retiree.get("active_employment_flag"):
        if size >= WORKING_AGED_EMPLOYER_SIZE:
            return "GROUP_PRIMARY_WORKING_AGED", "WORKING_AGED_LARGE_EMPLOYER"
        if size > 0:
            return "MEDICARE_PRIMARY", "WORKING_AGED_SMALL_EMPLOYER"

    if retiree.get("disability_entitlement_flag"):
        if size >= DISABILITY_EMPLOYER_SIZE:
            return "GROUP_PRIMARY", "DISABILITY_LARGE_EMPLOYER"
        if size > 0:
            return "MEDICARE_PRIMARY", "DISABILITY_SMALL_EMPLOYER"

    return "MEDICARE_PRIMARY", "MEDICARE_PRIMARY_RETIREE_COVERAGE"


# --- actuarial equivalence ---------------------------------------------------
def equivalence_results(gross_bps, net_bps):
    return {
        "gross_test_passed": gross_bps >= STANDARD_PART_D_GROSS_VALUE_BPS,
        "net_test_passed": net_bps >= STANDARD_PART_D_NET_VALUE_BPS,
        "equivalence_margin_bps": net_bps - STANDARD_PART_D_NET_VALUE_BPS,
    }


# --- HRA funding, forfeiture and claim eligibility ---------------------------
def hra_annual_credit_cents(plan_year, retiree, covered_months):
    """Floor to whole cents per month FIRST, then multiply by covered months."""
    if retiree["medicare_status"] == MEDICARE_ENROLLED:
        full_year = plan_year["hra_credit_medicare_cents"]
    else:
        full_year = plan_year["hra_credit_pre_medicare_cents"]
    monthly = full_year // 12
    return monthly * covered_months


def carryover_cap_cents(annual_credit_cents, carryover_cap_pct):
    """A fraction of THIS year's annual credit alone, truncated to whole cents."""
    product = Decimal(annual_credit_cents) * Decimal(str(carryover_cap_pct))
    return int(product.to_integral_value(rounding="ROUND_FLOOR"))


def year_end_forfeiture_cents(available_balance_cents, cap_cents):
    if available_balance_cents > cap_cents:
        return available_balance_cents - cap_cents
    return 0


def provisional_eligible_cents(submitted_cents, available_balance_cents):
    """The provisional variant caps against the balance only."""
    return min(submitted_cents, available_balance_cents)


def category_allowed_cents(expense_category, submitted_cents):
    if expense_category == "DENTAL_VISION_PREMIUM":
        return submitted_cents * DENTAL_VISION_REIMBURSEMENT_BPS // BPS_DENOMINATOR
    if expense_category == "QUALIFIED_MEDICAL":
        return min(submitted_cents, QUALIFIED_MEDICAL_PER_CLAIM_CAP_CENTS)
    return submitted_cents


def final_eligible_cents(expense_category, submitted_cents,
                         available_balance_cents, provisional_cents):
    """Category rule first, balance rule second.  The provisional amount is
    added back because it already sits in pending_hold_cents."""
    allowed = category_allowed_cents(expense_category, submitted_cents)
    return min(allowed, available_balance_cents + provisional_cents)


# --- premium invoice assembly ------------------------------------------------
def employer_subsidy_bps(group, credited_service_months):
    rate = SUBSIDY_BPS_BY_GROUP[group]
    if service_years(credited_service_months) >= LONG_SERVICE_YEARS:
        rate += LONG_SERVICE_BUMP_BPS
    return min(rate, MAX_SUBSIDY_BPS)


def premium_waterfall(plan_option, retiree, available_balance_cents):
    """Steps 1 through 8 of the pinned ten-step assembly.  Passing an available
    balance of 0 yields the enrollment's standing premium (steps 1-6 only)."""
    base = plan_option["monthly_premium_cents"]
    admin_fee = base * ADMIN_FEE_BPS // BPS_DENOMINATOR
    gross = base + admin_fee
    subsidy_bps = employer_subsidy_bps(retiree["grandfathered_group"],
                                       retiree["credited_service_months"])
    subsidy = gross * subsidy_bps // BPS_DENOMINATOR
    retiree_share = gross - subsidy
    hra_applied = min(available_balance_cents, retiree_share)
    return {
        "base_premium_cents": base,
        "admin_fee_cents": admin_fee,
        "gross_premium_cents": gross,
        "employer_subsidy_bps": subsidy_bps,
        "employer_subsidy_cents": subsidy,
        "retiree_share_cents": retiree_share,
        "hra_applied_cents": hra_applied,
        "net_due_cents": retiree_share - hra_applied,
    }


# --- liability valuation ----------------------------------------------------
def per_retiree_valuation(plan_year, retiree, method):
    epbo = (plan_year["assumed_annual_subsidy_cents"]
            * plan_year["assumed_payment_years"]
            * BPS_DENOMINATOR
            // (BPS_DENOMINATOR + plan_year["discount_rate_bps"]))

    full_elig = FULL_ELIGIBILITY_YEARS_BY_GROUP[retiree["grandfathered_group"]]
    assumed_retirement = full_elig + POST_ELIGIBILITY_SERVICE_YEARS
    sy = service_years(retiree["credited_service_months"])

    if method == "PROJECTED_UNIT_CREDIT":
        apbo = epbo * min(sy, assumed_retirement) // assumed_retirement
    else:
        apbo = epbo * min(sy, full_elig) // full_elig

    if sy < assumed_retirement:
        service_cost = epbo // assumed_retirement
    else:
        service_cost = 0

    return epbo, apbo, service_cost


# --- interval semantics -----------------------------------------------------
def coverage_intervals_collide(new_start, new_end, existing_start, existing_end):
    """Half-open coverage intervals; a null end means open-ended.  They collide
    when the new start is strictly earlier than the existing end and the
    existing start is strictly earlier than the new end."""
    left = existing_end is None or new_start < existing_end
    right = new_end is None or existing_start < new_end
    return left and right


def billing_periods_collide(new_start, new_end, existing_start, existing_end):
    """Closed billing periods; sharing a single endpoint is a collision."""
    return new_start <= existing_end and existing_start <= new_end


def coverage_class_permitted(medicare_status, coverage_class):
    allowed = COVERAGE_CLASS_BY_MEDICARE_POSTURE.get(medicare_status, ())
    return coverage_class in allowed
