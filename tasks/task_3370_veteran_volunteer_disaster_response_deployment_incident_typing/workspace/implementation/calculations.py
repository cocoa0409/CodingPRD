"""Calculation rules (SCAFFOLD section 1.3), implemented with pinned constants,
pinned evaluation order, and pinned rounding. Integer cents everywhere;
per-night round-half-up for lodging; no floats for money.
"""
import math
from decimal import Decimal, ROUND_HALF_UP
import timeutil
from constants import (
    PER_DIEM_DAILY_CENTS, TRAVEL_TIER_THRESHOLD_CENTS,
    TRAVEL_TIER_SHORT_CENTS, TRAVEL_TIER_LONG_CENTS,
    HAZARD_BASE, VULNERABLE_RESIDENT_BONUS, AGE_BOOST_PER_DAY, AGE_BOOST_CAP,
    P1_THRESHOLD, P2_THRESHOLD, FOB_UTILITY_SURCHARGE,
)


def stipend_for_days(days):
    """deployment_stipend_cents, pinned 5-step order:
    1. days (supplied by variant)  2. per_diem = days * 6500
    3. tier = LONG iff per_diem >= 200000  4. travel = 45000 or 15000
    5. stipend = per_diem + travel (exact integer cents)."""
    per_diem_total = days * PER_DIEM_DAILY_CENTS
    if per_diem_total >= TRAVEL_TIER_THRESHOLD_CENTS:
        travel = TRAVEL_TIER_LONG_CENTS
    else:
        travel = TRAVEL_TIER_SHORT_CENTS
    return per_diem_total + travel


def final_stipend_days(checked_in_iso, demobed_iso):
    """Final variant day count: ceil(elapsed / 24h), minimum 1."""
    delta = timeutil.parse_iso(demobed_iso) - timeutil.parse_iso(checked_in_iso)
    days = math.ceil(delta.total_seconds() / 86400.0)
    return max(1, days)


def shift_hours(starts_iso, ends_iso):
    """Shift hours: ceil(elapsed / 1h), minimum 1."""
    delta = timeutil.parse_iso(ends_iso) - timeutil.parse_iso(starts_iso)
    hours = math.ceil(delta.total_seconds() / 3600.0)
    return max(1, hours)


def lodging_stay_cost(nightly_rate_cents, checked_in_iso, demobed_iso):
    """fob_lodging_cost_cents. PINNED ORDER: round each night's charge to
    integer cents half-up FIRST, then multiply by the night count.
    nights = UTC calendar dates from date(check-in) inclusive to
    date(demobe) exclusive, minimum 1."""
    ci = timeutil.parse_iso(checked_in_iso)
    dm = timeutil.parse_iso(demobed_iso)
    nights = (dm.date() - ci.date()).days
    nights = max(1, nights)
    per_night = (Decimal(nightly_rate_cents) * (Decimal(1) + FOB_UTILITY_SURCHARGE)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return nights * int(per_night)


def priority_score_and_tier(work_order, now):
    """work_order_priority_score (calc): base + vulnerable bonus + age boost,
    age boost = min(20, floor(wait_hours/24) * 5); score capped at 100;
    tier P1 >= 80, P2 >= 50, else P3."""
    base = HAZARD_BASE[work_order["hazard_kind"]]
    bonus = VULNERABLE_RESIDENT_BONUS if work_order["vulnerable_resident"] else 0
    wait = now - timeutil.parse_iso(work_order["created_at"])
    wait_hours = wait.total_seconds() / 3600.0
    age_boost = min(AGE_BOOST_CAP, int(math.floor(wait_hours / 24.0)) * AGE_BOOST_PER_DAY)
    score = min(100, base + bonus + age_boost)
    if score >= P1_THRESHOLD:
        tier = "P1"
    elif score >= P2_THRESHOLD:
        tier = "P2"
    else:
        tier = "P3"
    return score, tier
