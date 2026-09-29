"""Arithmetic and algorithmic rules (PRD sections 2.7, 3.2, 3.3, 3.4, 3.9)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")
ONE = Decimal("1")

COVERED_UNIT_THRESHOLD = 20
DECLARE_ZERO_CEILING = Decimal("5")
DECLARE_NEAREST_5_CEILING = Decimal("50")
SODIUM_ZERO_CEILING = Decimal("5")
SODIUM_NEAREST_5_CEILING = Decimal("140")
UNLIMITED_REPEAT_CAP = 3
EXEMPTION_DAY_LIMIT = 60
TOLERANCE_FLOOR_CALORIES = 20
TOLERANCE_FRACTION = Decimal("0.20")
GRACE_DAYS_NO_EXTRA_REQUIREMENT = 30
GRACE_DAYS_WITH_EXTRA_REQUIREMENT = 14
MIN_COVERED_ITEMS_FOR_PACKET = 1
BASE_VIOLATION_CENTS = Decimal("50000")
ENHANCED_MULTIPLIER = Decimal("1.5")
FEE_TIER_1_CEILING_CENTS = 100000
FEE_TIER_2_CEILING_CENTS = 250000
FEE_RATE_TIER_1 = Decimal("0.05")
FEE_RATE_TIER_2 = Decimal("0.08")
FEE_RATE_TIER_3 = Decimal("0.12")
VARIANCE_COOLING_DAYS = 7


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value):
    """Two decimal places, rounded half up."""
    return dec(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Integer, rounded half up."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def num(value):
    """Render a Decimal for JSON without float noise."""
    if value is None:
        return None
    value = q2(value)
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def component_calories(calories_per_100g, grams):
    return q2(dec(calories_per_100g) * dec(grams) / Decimal("100"))


def component_sodium(sodium_mg_per_100g, grams):
    return q2(dec(sodium_mg_per_100g) * dec(grams) / Decimal("100"))


def declare_calories(total):
    """FDA calorie declaration ladder, applied once to an already-summed total."""
    total = q2(total)
    if total < DECLARE_ZERO_CEILING:
        return 0
    if total <= DECLARE_NEAREST_5_CEILING:
        return rhu_int(total / Decimal("5")) * 5
    return rhu_int(total / Decimal("10")) * 10


def declare_sodium(total):
    """Sodium declaration ladder, applied once to an already-summed total."""
    total = q2(total)
    if total < SODIUM_ZERO_CEILING:
        return 0
    if total <= SODIUM_NEAREST_5_CEILING:
        return rhu_int(total / Decimal("5")) * 5
    return rhu_int(total / Decimal("10")) * 10


def display_calorie_text(minimum, maximum):
    """'320 Cal' when the endpoints agree, otherwise '320-540 Cal'."""
    if minimum is None and maximum is None:
        return None
    if minimum is None:
        minimum = maximum
    if maximum is None:
        maximum = minimum
    if minimum == maximum:
        return "%s Cal" % minimum
    return "%s-%s Cal" % (minimum, maximum)


def reprint_tolerance(prior_max):
    """max(20, round_half_up(prior_max * 0.20))."""
    scaled = rhu_int(dec(prior_max) * TOLERANCE_FRACTION)
    return max(TOLERANCE_FLOOR_CALORIES, scaled)


def reprint_required(prior_max, new_max):
    """True when the change reaches the tolerance -- delta >= tolerance."""
    if prior_max is None:
        return False
    if new_max is None:
        return False
    delta = abs(int(new_max) - int(prior_max))
    return delta >= reprint_tolerance(prior_max)


def merge_windows(windows):
    """Interval merge with the exact one-day adjacency rule.

    ``windows`` is a list of (start_date, end_date) pairs already restricted to
    the reviewed year.  Sorted by start_date ascending then end_date ascending;
    a window opens a new span when nothing has accumulated yet or when its
    start_date falls more than one day after the accumulated span's end.
    """
    ordered = sorted(windows, key=lambda w: (w[0], w[1]))
    spans = []
    for start, end in ordered:
        if not spans:
            spans.append([start, end])
            continue
        current = spans[-1]
        if (start - current[1]).days > 1:
            spans.append([start, end])
        else:
            if end > current[1]:
                current[1] = end
    return [(s[0], s[1]) for s in spans]


def merged_day_count(windows):
    total = 0
    for start, end in merge_windows(windows):
        total += (end - start).days + 1
    return total


def fee_rate(base_penalty_cents):
    if base_penalty_cents <= FEE_TIER_1_CEILING_CENTS:
        return FEE_RATE_TIER_1
    if base_penalty_cents <= FEE_TIER_2_CEILING_CENTS:
        return FEE_RATE_TIER_2
    return FEE_RATE_TIER_3


def penalty_amounts(violation_unit_count, enforcement_tier):
    """Returns (base_penalty_cents, admin_fee_cents, penalty_total_cents)."""
    multiplier = ENHANCED_MULTIPLIER if enforcement_tier == "ENHANCED" else ONE
    base = rhu_int(BASE_VIOLATION_CENTS * dec(violation_unit_count) * multiplier)
    fee = rhu_int(dec(base) * fee_rate(base))
    return base, fee, base + fee


def grace_days(extra_requirement):
    if extra_requirement == "NONE":
        return GRACE_DAYS_NO_EXTRA_REQUIREMENT
    return GRACE_DAYS_WITH_EXTRA_REQUIREMENT


def add_days(instant, days):
    return instant + timedelta(days=days)


def group_endpoints(members, selection_mode, selection_limit):
    """Per-choice-group calorie minimum and maximum.

    ``members`` is the list of component calorie Decimals of one choice group,
    already ordered descending by component_calories with ties broken by
    ascending created_at.
    """
    if not members:
        return Decimal("0"), Decimal("0")
    largest = members[0]
    smallest = members[-1]
    if selection_mode == "EXACTLY_ONE":
        return smallest, largest
    if selection_mode == "UP_TO_N":
        take = selection_limit if selection_limit is not None else len(members)
        take = min(take, len(members))
        return Decimal("0"), q2(sum(members[:take]))
    # UNLIMITED
    return Decimal("0"), q2(largest * Decimal(UNLIMITED_REPEAT_CAP))
