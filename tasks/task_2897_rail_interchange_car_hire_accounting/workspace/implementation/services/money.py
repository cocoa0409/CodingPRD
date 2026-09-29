"""Monetary and quantity arithmetic (PRD sections 2.6, 3.4, 3.5, 3.6, 3.7, 3.8).

Every rounding step in this system is ROUND_HALF_UP; nothing here uses float
arithmetic for a figure that reaches the wire.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import db

ZERO = Decimal("0")
TWO_PLACES = Decimal("0.01")


def half_up_int(value):
    """Round a Decimal to a whole number of cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def half_up_2(value):
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def num2(value):
    """Serialise a two-decimal quantity as a JSON number."""
    if value is None:
        return None
    return float(half_up_2(value))


def elapsed_hours(start_at, end_at):
    """Wall interval in hours, to two decimal places (PRD section 3.4)."""
    seconds = Decimal(str((end_at - start_at).total_seconds()))
    return half_up_2(seconds / Decimal(3600))


def chargeable_hours(elapsed, free_time_hours):
    free = Decimal(str(free_time_hours))
    value = Decimal(elapsed) - free
    if value < ZERO:
        value = ZERO
    return half_up_2(value)


def chargeable_days(hours_value):
    """Any part of a day counts as a whole day (PRD section 3.4)."""
    hours_value = Decimal(hours_value)
    if hours_value <= ZERO:
        return 0
    return int((hours_value / Decimal(24)).to_integral_value(rounding=ROUND_CEILING))


def per_diem_time_cents(car_type, hours_value):
    """Marginal two-tier per diem ladder."""
    day_count = chargeable_days(hours_value)
    threshold = int(car_type["tier2_threshold_days"])
    tier1_days = min(day_count, threshold)
    tier2_days = max(0, day_count - threshold)
    cents = tier1_days * int(car_type["per_diem_rate_cents"]) + tier2_days * int(
        car_type["tier2_per_diem_rate_cents"]
    )
    return day_count, cents


def time_component(car_type, hours_value):
    """Returns (chargeable_days, time_component_cents)."""
    if car_type["time_component_mode"] == "PER_DIEM":
        return per_diem_time_cents(car_type, hours_value)
    # HOURLY -- the day ladder is not used and the segment reports 0 days
    cents = half_up_int(Decimal(hours_value) * Decimal(int(car_type["hourly_rate_cents"])))
    return 0, cents


def mileage_component(car_type, miles, load_status):
    """One rounding per segment (PRD section 3.4)."""
    miles = int(miles or 0)
    if miles < 0:
        miles = 0
    billable = miles
    if car_type["loaded_mileage_only"] and load_status == "EMPTY":
        billable = 0
    rate = Decimal(int(car_type["mileage_rate_millicents_per_mile"]))
    return half_up_int(Decimal(billable) * rate / Decimal(1000))


def reclaim_credit_cents(time_component_cents, chargeable_hours_value, effective_hours, split_pct):
    """The split multiplies inside the single rounding (PRD section 3.5)."""
    time_cents = Decimal(int(time_component_cents))
    charge_hours = Decimal(chargeable_hours_value)
    if charge_hours <= ZERO or time_cents == ZERO:
        return 0
    raw = half_up_int(
        time_cents * Decimal(effective_hours) / charge_hours * Decimal(str(split_pct))
    )
    return min(raw, int(time_component_cents))


def reverse_route_penalty_cents(time_component_cents):
    return half_up_int(Decimal(int(time_component_cents)) * Decimal(db.REVERSE_ROUTE_PENALTY_PCT))


def repair_labor_cents(labor_hours):
    return half_up_int(Decimal(labor_hours) * Decimal(db.REPAIR_LABOR_RATE_CENTS_PER_HOUR))


def repair_handling_fee_cents(subtotal_cents, responsible_road_id, billing_road_id):
    if responsible_road_id == billing_road_id:
        return 0
    return half_up_int(Decimal(int(subtotal_cents)) * Decimal(db.REPAIR_HANDLING_FEE_PCT))


def clearinghouse_fee_cents(pre_fee_net_cents):
    """Flat selected tier on the absolute pre-fee net (PRD section 3.8)."""
    basis = abs(int(pre_fee_net_cents))
    if basis <= db.FEE_TIER_BREAK_CENTS:
        rate = Decimal(db.FEE_TIER1_PCT)
    else:
        rate = Decimal(db.FEE_TIER2_PCT)
    return half_up_int(Decimal(basis) * rate)


def utilization_pct(serviceable_foreign_count, owned_car_count):
    if not owned_car_count:
        return Decimal("0.00")
    return half_up_2(
        Decimal(100) * Decimal(int(serviceable_foreign_count)) / Decimal(int(owned_car_count))
    )
