"""Calculation rules: WARN counting, composite scoring, adverse impact, severance."""
import math
from datetime import timedelta
from decimal import Decimal

from core import D, parse_date, rhu, rhu_int

MIN_PART_TIME_HOURS = 20
WEIGHT_TOTAL = 100

FOUR_FIFTHS_THRESHOLD = Decimal("0.80")
SD_THRESHOLD = Decimal("2.0")
MIN_FOCAL_CLASS_SIZE = 3

WEEKS_CAP = Decimal(52)
RELEASE_BONUS_WEEKS = Decimal(2)
WEEKS_PER_YEAR_DIVISOR = Decimal(52)

SUBSIDY_TIER_1_CEILING = 1000000
SUBSIDY_TIER_2_CEILING = 2500000
SUBSIDY_RATE = Decimal("0.65")
OUTPLACEMENT_STANDARD_FEE_CENTS = 120000
OUTPLACEMENT_PREMIUM_FEE_CENTS = 350000
NOTICE_DAILY_DIVISOR = Decimal(7)

OWBPA_PROTECTED_AGE = 40
GROUP_CONSIDERATION_DAYS = 45
INDIVIDUAL_CONSIDERATION_DAYS = 21
UNPROTECTED_CONSIDERATION_DAYS = 14
REVOCATION_DAYS = 7

RESTRICTION_DAYS = 90

LOSS_STATUSES = ("PENDING_SEPARATION", "SEPARATED")
WORKFORCE_STATUSES = ("ACTIVE", "PENDING_SEPARATION", "SEPARATED")
POOL_STATUSES = ("PROPOSED", "SELECTED", "EXEMPTED", "SEPARATED")
SELECTED_STATUSES = ("SELECTED", "SEPARATED")
RESERVE_STATUSES = ("ISSUED", "SIGNED", "EFFECTIVE")


# ---------------------------------------------------------------------------
# warn_employment_loss_count
# ---------------------------------------------------------------------------
def window_start_for_site(employees):
    dates = [parse_date(e["separation_date"]) for e in employees
             if e["employment_status"] in LOSS_STATUSES and e["separation_date"]]
    return min(dates) if dates else None


def warn_determination(employees, rule):
    """Run the jurisdictional employment-loss count for one site under one rule.

    Returns a dict carrying the counts, the rounded percentage, the threshold
    outcome and the trigger classification.
    """
    blank = {
        "window_start_date": None,
        "window_end_date": None,
        "employment_loss_count": 0,
        "workforce_count": 0,
        "loss_percent": Decimal("0.00"),
        "threshold_met": False,
        "trigger_type": "NONE",
        "required_notice_days": 0,
    }
    if rule is None:
        return dict(blank)

    window_start = window_start_for_site(employees)
    if window_start is None:
        return dict(blank)

    window_end = window_start + timedelta(days=int(rule["window_days"]))
    federal = rule["jurisdiction"] == "FEDERAL"

    def in_window(day):
        if day is None:
            return False
        if federal:
            return window_start <= day < window_end
        return window_start <= day <= window_end

    loss_count = 0
    for emp in employees:
        if emp["employment_status"] not in LOSS_STATUSES:
            continue
        sep = parse_date(emp["separation_date"])
        if not in_window(sep):
            continue
        if not rule["counts_part_time"] and emp["is_part_time"]:
            continue
        hire = parse_date(emp["hire_date"])
        if (sep - hire).days < int(rule["min_service_days"]):
            continue
        loss_count += 1

    workforce_count = 0
    for emp in employees:
        if emp["employment_status"] not in WORKFORCE_STATUSES:
            continue
        hire = parse_date(emp["hire_date"])
        if hire > window_start:
            continue
        if not rule["counts_part_time"] and emp["is_part_time"]:
            continue
        workforce_count += 1

    if workforce_count == 0:
        loss_percent = Decimal("0.00")
    else:
        loss_percent = rhu(D(100) * D(loss_count) / D(workforce_count), 2)

    min_percent = D(rule["min_percent"])
    count_test = loss_count >= int(rule["min_loss_count"])
    percent_test = (min_percent == 0) or (loss_percent >= min_percent)
    absolute_test = int(rule["absolute_count"]) > 0 and loss_count >= int(rule["absolute_count"])
    threshold_met = (count_test and percent_test) or absolute_test

    if threshold_met and loss_count == workforce_count:
        trigger_type = "PLANT_CLOSING"
    elif threshold_met:
        trigger_type = "MASS_LAYOFF"
    else:
        trigger_type = "NONE"

    return {
        "window_start_date": window_start,
        "window_end_date": window_end,
        "employment_loss_count": loss_count,
        "workforce_count": workforce_count,
        "loss_percent": loss_percent,
        "threshold_met": threshold_met,
        "trigger_type": trigger_type,
        "required_notice_days": int(rule["notice_days"]),
    }


# ---------------------------------------------------------------------------
# selection_composite_score
# ---------------------------------------------------------------------------
def composite_score(criteria, scores):
    by_code = {row["criterion_code"]: row["score"] for row in scores}
    total = Decimal(0)
    for criterion in criteria:
        score = D(by_code[criterion["criterion_code"]])
        total += score * D(criterion["weight_pct"]) / D(WEIGHT_TOTAL)
    return rhu(total, 2)


# ---------------------------------------------------------------------------
# adverse_impact_statistic
# ---------------------------------------------------------------------------
def adverse_impact(pool_rows, method):
    """pool_rows: list of (selection_status, demographic_code).

    Returns a dict of computed fields, or raises ValueError('insufficient').
    """
    total = len(pool_rows)
    selected = sum(1 for status, _ in pool_rows if status in SELECTED_STATUSES)
    if total == 0 or selected == 0:
        raise ValueError("insufficient")

    classes = {}
    for status, code in pool_rows:
        entry = classes.setdefault(code, {"n": 0, "s": 0})
        entry["n"] += 1
        if status in SELECTED_STATUSES:
            entry["s"] += 1

    ordered = sorted(
        classes.items(),
        key=lambda item: (D(item[1]["s"]) / D(item[1]["n"]), item[0]),
    )
    focal_code, focal = ordered[0]
    n_f = focal["n"]
    s_f = focal["s"]

    if total - n_f == 0:
        raise ValueError("insufficient")

    focal_rate = rhu(D(s_f) / D(n_f), 4)
    reference_rate = rhu(D(selected - s_f) / D(total - n_f), 4)
    if reference_rate == 0:
        raise ValueError("insufficient")

    shortfall = int(math.ceil(float(reference_rate * D(n_f)))) - s_f
    shortfall_count = shortfall if shortfall > 0 else 0
    small_sample = n_f < MIN_FOCAL_CLASS_SIZE

    result = {
        "pool_count": total,
        "selected_count": selected,
        "focal_class_code": focal_code,
        "focal_pool_count": n_f,
        "focal_selected_count": s_f,
        "focal_rate": focal_rate,
        "reference_rate": reference_rate,
        "impact_ratio": None,
        "standard_deviations": None,
        "shortfall_count": shortfall_count,
        "small_sample_suppressed": small_sample,
    }

    if method == "IMPACT_RATIO":
        ratio = rhu(focal_rate / reference_rate, 4)
        result["impact_ratio"] = ratio
        flagged = (ratio < FOUR_FIFTHS_THRESHOLD) and not small_sample
    else:
        expected = D(n_f) * D(selected) / D(total)
        variance = (D(selected) * D(total - selected) * D(n_f) * D(total - n_f)) / (
            D(total) * D(total) * D(total - 1)
        )
        sd = variance.sqrt()
        if sd == 0:
            sds = Decimal("0.0000")
        else:
            sds = rhu((expected - D(s_f)) / sd, 4)
        result["standard_deviations"] = sds
        flagged = (sds >= SD_THRESHOLD) and not small_sample

    result["status"] = "FLAGGED" if flagged else "COMPUTED"
    return result


# ---------------------------------------------------------------------------
# severance_award_cents + separation_cost_rollup
# ---------------------------------------------------------------------------
def base_weeks_for(years):
    y = D(years)
    if years < 2:
        weeks = Decimal(2)
    elif years < 5:
        weeks = Decimal(4) + Decimal(1) * (y - 2)
    elif years < 10:
        weeks = Decimal(7) + Decimal("1.5") * (y - 5)
    else:
        weeks = Decimal("14.5") + Decimal(2) * (y - 10)
    return min(weeks, WEEKS_CAP)


def price_offer(employee, variant, required_notice_days, notice_days_before_separation):
    """Runs severance_award_cents then separation_cost_rollup in the pinned order."""
    # (1) weekly rate rounded to whole cents BEFORE any multiplication
    weekly_rate_cents = rhu_int(D(employee["annual_base_cents"]) / WEEKS_PER_YEAR_DIVISOR)

    # (2) tier on completed years of service
    years = employee["years_of_service"] or 0
    base_weeks = base_weeks_for(years)

    # (3) variant
    if variant == "STANDARD":
        weeks_awarded = Decimal(int(base_weeks.to_integral_value(rounding="ROUND_FLOOR")))
    else:
        weeks_awarded = base_weeks + RELEASE_BONUS_WEEKS

    # (4) product rounded half up exactly once
    base_severance_cents = rhu_int(D(weekly_rate_cents) * weeks_awarded)

    # (5) notice shortfall
    required = int(required_notice_days or 0)
    actual = notice_days_before_separation
    actual = 0 if actual is None else int(actual)
    notice_shortfall_days = max(0, required - actual)
    daily_rate_cents = rhu_int(D(weekly_rate_cents) / NOTICE_DAILY_DIVISOR)
    notice_pay_offset_cents = rhu_int(D(daily_rate_cents) * D(notice_shortfall_days))

    # (6) benefit tier keyed on the pre-benefit subtotal
    pre_benefit_subtotal = base_severance_cents + notice_pay_offset_cents
    if pre_benefit_subtotal < SUBSIDY_TIER_1_CEILING:
        benefit_subsidy_months = 3
    elif pre_benefit_subtotal < SUBSIDY_TIER_2_CEILING:
        benefit_subsidy_months = 6
    else:
        benefit_subsidy_months = 9
    monthly_subsidy_cents = rhu_int(D(employee["monthly_premium_cents"]) * SUBSIDY_RATE)
    benefit_subsidy_cents = benefit_subsidy_months * monthly_subsidy_cents

    # (7) outplacement follows the benefit tier
    if benefit_subsidy_months >= 6:
        outplacement_tier = "PREMIUM"
        outplacement_fee_cents = OUTPLACEMENT_PREMIUM_FEE_CENTS
    else:
        outplacement_tier = "STANDARD"
        outplacement_fee_cents = OUTPLACEMENT_STANDARD_FEE_CENTS

    # (8) total
    total_separation_cost_cents = (
        base_severance_cents + notice_pay_offset_cents
        + benefit_subsidy_cents + outplacement_fee_cents
    )

    return {
        "weekly_rate_cents": weekly_rate_cents,
        "weeks_awarded": weeks_awarded,
        "base_severance_cents": base_severance_cents,
        "notice_shortfall_days": notice_shortfall_days,
        "notice_pay_offset_cents": notice_pay_offset_cents,
        "benefit_subsidy_months": benefit_subsidy_months,
        "benefit_subsidy_cents": benefit_subsidy_cents,
        "outplacement_tier": outplacement_tier,
        "outplacement_fee_cents": outplacement_fee_cents,
        "total_separation_cost_cents": total_separation_cost_cents,
    }


def consideration_days_for(age, plan_selected_count):
    if age is not None and age >= OWBPA_PROTECTED_AGE:
        if plan_selected_count >= 2:
            return GROUP_CONSIDERATION_DAYS
        return INDIVIDUAL_CONSIDERATION_DAYS
    return UNPROTECTED_CONSIDERATION_DAYS


def outplacement_tier_for_months(months):
    if months >= 6:
        return "PREMIUM"
    if months >= 1:
        return "STANDARD"
    return "NONE"
