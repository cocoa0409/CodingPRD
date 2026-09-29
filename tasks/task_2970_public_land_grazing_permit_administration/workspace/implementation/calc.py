"""Numeric conventions (PRD 2.8) and every named calculation (PRD 3.4 - 3.12)."""

import math
from decimal import Decimal, ROUND_HALF_UP

import constants as K

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")
ONE = Decimal("1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half-up to the given number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def aums2(value):
    return rhu(value, 2)


def pct4(value):
    return rhu(value, 4)


def score2(value):
    return rhu(value, 2)


def cents(value):
    """Round a money figure half-up to a whole cent."""
    return int(rhu(value, 0))


def floor_int(value):
    return int(math.floor(dec(value)))


def ceil_int(value):
    return int(math.ceil(dec(value)))


# ------------------------------------------------------------- forage arithmetic


def whole_days(entry, exit_):
    """Whole days in the half-open window [entry, exit)."""
    return (exit_ - entry).days


def forage_aums(head_count, livestock_kind, days):
    """PRD 3.4: head x animal-unit-equivalent x days / 30, rounded half-up to 2dp
    exactly once."""
    aue = K.ANIMAL_UNIT_EQUIVALENT[livestock_kind]
    return aums2(dec(head_count) * aue * dec(days) / dec(K.DAYS_PER_AUM))


# ------------------------------------------------------------- qualification


def qualified_aums(base_property_type, carrying_capacity_aums):
    """PRD 3.2: capacity x factor, floored to a whole AUM."""
    factor = (K.LAND_QUALIFICATION_FACTOR if base_property_type == "LAND"
              else K.LIVESTOCK_QUALIFICATION_FACTOR)
    return floor_int(dec(carrying_capacity_aums) * factor)


# ------------------------------------------------------------------ capacity


def effective_capacity(total_permitted_aums, stocking_adjustment_pct):
    """PRD 2.9: total_permitted_aums x (1 - pct), floored."""
    return floor_int(dec(total_permitted_aums) * (ONE - dec(stocking_adjustment_pct)))


def reauthorized_aums(authorized_aums_at_issue, stocking_adjustment_pct):
    """PRD 3.10 hop three: snapshot x (1 - pct), floored."""
    return floor_int(dec(authorized_aums_at_issue) * (ONE - dec(stocking_adjustment_pct)))


def posture(stocking_adjustment_pct):
    """PRD 3.10 hop two."""
    value = dec(stocking_adjustment_pct)
    if value == ONE:
        return "CLOSED"
    if value > 0:
        return "RESTRICTED"
    return "OPEN"


# ------------------------------------------------------------- use-bill money


def admin_fee_for(base_amount_cents):
    """PRD 3.6 step three -- read off base_amount_cents, never the total."""
    if base_amount_cents < K.ADMIN_FEE_TIER_1_CEILING_CENTS:
        return K.ADMIN_FEE_TIER_1_CENTS
    if base_amount_cents < K.ADMIN_FEE_TIER_2_CEILING_CENTS:
        return K.ADMIN_FEE_TIER_2_CENTS
    return K.ADMIN_FEE_TIER_3_CENTS


def use_bill_money(billed_aums):
    """PRD 3.6 steps two, three and four."""
    base = cents(dec(billed_aums) * dec(K.GRAZING_FEE_RATE_CENTS_PER_AUM))
    admin = admin_fee_for(base)
    return {
        "billed_aums": aums2(billed_aums),
        "fee_rate_cents_per_aum": K.GRAZING_FEE_RATE_CENTS_PER_AUM,
        "base_amount_cents": base,
        "admin_fee_cents": admin,
        "penalty_amount_cents": 0,
        "total_amount_cents": base + admin,
    }


def final_billed_aums(actual_aums_total, authorized_aums, nonuse_aums):
    """PRD 3.6 final variant: max(actual_aums_total, floor(0.25 x billable))."""
    floor_part = Decimal(floor_int(
        K.MIN_BILLABLE_FRACTION * dec(authorized_aums - nonuse_aums)))
    actual = dec(actual_aums_total)
    return actual if actual > floor_part else floor_part


# --------------------------------------------------------- unauthorized use


def trespass_money(unauthorized_aums, willfulness, prior_billed_incident_count):
    """PRD 3.11 steps two through seven."""
    billed = ceil_int(unauthorized_aums)
    base = billed * K.FORAGE_VALUE_CENTS_PER_AUM
    multiplier = K.WILLFULNESS_MULTIPLIER[willfulness]
    repeat = ONE + K.REPEAT_FACTOR_STEP * dec(prior_billed_incident_count)
    if repeat > K.REPEAT_FACTOR_CEILING:
        repeat = K.REPEAT_FACTOR_CEILING
    penalty = cents(dec(base) * (multiplier - ONE) * repeat)
    return {
        "billed_aums": aums2(billed),
        "fee_rate_cents_per_aum": K.FORAGE_VALUE_CENTS_PER_AUM,
        "base_amount_cents": base,
        "admin_fee_cents": 0,
        "penalty_amount_cents": penalty,
        "total_amount_cents": base + penalty,
    }


# ------------------------------------------------------------------- health


def composite_score(upland, riparian, water_quality):
    return score2(dec(upland) * K.UPLAND_WEIGHT
                  + dec(riparian) * K.RIPARIAN_WEIGHT
                  + dec(water_quality) * K.WATER_QUALITY_WEIGHT)


def determination_for(score):
    if dec(score) >= K.HEALTH_MEETING_THRESHOLD:
        return "MEETING"
    if dec(score) >= K.HEALTH_NOT_MEETING_THRESHOLD:
        return "MEETING_WITH_PROBLEMS"
    return "NOT_MEETING"


def recommended_reduction(monitoring_method, standards_not_met,
                         causal_factor_is_livestock, observed_utilization_pct,
                         determination):
    """PRD 3.7. Zero unless the determination is NOT_MEETING."""
    if determination != "NOT_MEETING":
        return pct4(0)
    if monitoring_method == "INDICATOR_ASSESSMENT":
        raw = K.STANDARD_NOT_MET_REDUCTION_STEP * dec(len(standards_not_met or []))
        if causal_factor_is_livestock:
            raw += K.LIVESTOCK_CAUSAL_REDUCTION_ADDER
        if raw > K.MAX_RECOMMENDED_REDUCTION_PCT:
            raw = K.MAX_RECOMMENDED_REDUCTION_PCT
        return pct4(raw)
    observed = observed_utilization_pct
    if observed is None or dec(observed) <= K.TARGET_UTILIZATION_PCT:
        return pct4(0)
    raw = (dec(observed) - dec(K.TARGET_UTILIZATION_PCT)) / dec(observed)
    if raw > K.MAX_RECOMMENDED_REDUCTION_PCT:
        raw = K.MAX_RECOMMENDED_REDUCTION_PCT
    return pct4(raw)


# ---------------------------------------------------------------- cost share


def prorata_shares(pot_cents, weights):
    """PRD 3.12 passes one and two. weights is a list of (key, aums, created_at,
    seq) tuples; returns {key: cents} landing on pot_cents exactly."""
    total_aums = sum(item[1] for item in weights)
    if not weights or total_aums <= 0:
        return {}
    shares = {}
    for key, aums, _created_at, _seq in weights:
        shares[key] = floor_int(dec(pot_cents) * dec(aums) / dec(total_aums))
    remainder = pot_cents - sum(shares.values())
    if remainder > 0:
        ranked = sorted(weights, key=lambda item: (-item[1], item[2], item[3]))
        for index in range(remainder):
            shares[ranked[index % len(ranked)][0]] += 1
    return shares
