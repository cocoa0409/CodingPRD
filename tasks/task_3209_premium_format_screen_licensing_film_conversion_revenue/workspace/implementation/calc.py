"""Calculation rules per SCAFFOLD §1.3 and PRD §2.6, §3."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

TIER1_CAP_CENTS = 10_000_000
TIER2_CAP_CENTS = 25_000_000
FORECAST_DAILY_FRACTION = Decimal("0.5")
HOLD_OVER_ADMISSION_THRESHOLD = Decimal("0.65")

BASE_RATE_CENTS = {
    "PREMIUM_2D": 200_000_000,
    "PREMIUM_3D": 350_000_000,
    "PREMIUM_70MM": 500_000_000,
}
PER_MIN_RATE_CENTS = {
    "PREMIUM_2D": 1_200_000,
    "PREMIUM_3D": 1_800_000,
    "PREMIUM_70MM": 2_500_000,
}

SEVERITY_WEIGHT = {"INFO": 1, "WARNING": 3, "CRITICAL": 10}


def round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def conversion_post_cost_estimate(target_format: str, runtime_minutes: int) -> int:
    return BASE_RATE_CENTS[target_format] + runtime_minutes * PER_MIN_RATE_CENTS[target_format]


def committed_screen_seconds(days: int, showings_per_day: int, runtime_minutes: int) -> int:
    return days * showings_per_day * runtime_minutes * 60


def tiered_marginal_share(gross_cents, tier1_pct, tier2_pct, tier3_pct) -> Decimal:
    """Apply tiered marginal share to a cumulative gross.

    gross_cents may be int or Decimal. Returns Decimal (unrounded).
    Boundaries: at exactly TIER1_CAP, tier 1 still applies (<=).
    """
    gross = Decimal(str(gross_cents))
    t1 = Decimal(str(tier1_pct))
    t2 = Decimal(str(tier2_pct))
    t3 = Decimal(str(tier3_pct))
    cap1 = Decimal(TIER1_CAP_CENTS)
    cap2 = Decimal(TIER2_CAP_CENTS)
    if gross <= cap1:
        return gross * t1
    if gross <= cap2:
        return cap1 * t1 + (gross - cap1) * t2
    return cap1 * t1 + (cap2 - cap1) * t2 + (gross - cap2) * t3


def tiered_marginal_share_per_day(running_gross_before: int, day_gross: int,
                                  tier1_pct, tier2_pct, tier3_pct) -> Decimal:
    """Share for a single day's receipts, splitting at tier boundaries."""
    after = Decimal(running_gross_before + day_gross)
    before = Decimal(running_gross_before)
    share_after = tiered_marginal_share(after, tier1_pct, tier2_pct, tier3_pct)
    share_before = tiered_marginal_share(before, tier1_pct, tier2_pct, tier3_pct)
    return share_after - share_before


def per_screen_attendance_ratio(weekly_admissions: int, seating_capacity: int,
                                showings_per_day: int, days_elapsed: int) -> Decimal:
    denominator = seating_capacity * showings_per_day * days_elapsed
    if denominator == 0:
        return Decimal("0")
    return Decimal(weekly_admissions) / Decimal(denominator)


def quality_score_arithmetic(alerts_in_window: list) -> Decimal:
    count = max(1, len(alerts_in_window))
    total = sum(SEVERITY_WEIGHT[a["severity"]] for a in alerts_in_window)
    return Decimal(total) / Decimal(count)


def quality_score_recency(alerts_in_window: list, clock_now) -> Decimal:
    count = max(1, len(alerts_in_window))
    total = Decimal("0")
    for a in alerts_in_window:
        age_seconds = (clock_now - a["_raised_at_dt"]).total_seconds()
        age_days = int(age_seconds // 86400)
        if age_days < 0:
            age_days = 0
        if age_days > 29:
            age_days = 29
        recency_weight = Decimal(1) - (Decimal(age_days) / Decimal(30))
        total += Decimal(SEVERITY_WEIGHT[a["severity"]]) * recency_weight
    return total / Decimal(count)


def holdover_score(per_screen_attendance_ratio_val, format_premium_uplift, week_over_week_growth) -> Decimal:
    ratio = Decimal(str(per_screen_attendance_ratio_val))
    uplift = Decimal(str(format_premium_uplift))
    growth = Decimal(str(week_over_week_growth))
    if growth > Decimal("1.0"):
        growth = Decimal("1.0")
    return Decimal("0.5") * ratio + Decimal("0.3") * uplift + Decimal("0.2") * growth
