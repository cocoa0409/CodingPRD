"""Interpreter compensation: one formula, three variants (PRD 3.8).

Each monetary component is rounded to whole cents half up *before* the three
are summed; summing unrounded components and rounding once is a different
number and is not the rule.
"""
from decimal import Decimal

from store import db
from util import dec, hours_two_dp, parse_dt, round_half_up_cents

TIER_RATE_FIELD = {
    "MASTER": "master_hourly_cents",
    "CERTIFIED": "certified_hourly_cents",
    "REGISTERED": "registered_hourly_cents",
    "PROVISIONAL": "provisional_hourly_cents",
}


def _billable_from_window(start, end, minimum_call_hours):
    """Quarter-hour round-up, then the minimum-call floor."""
    delta = end - start
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    if micros < 0:
        micros = 0
    quarters = -(-micros * 4 // 3600000000)
    rounded = Decimal(quarters) / Decimal(4)
    floor = dec(minimum_call_hours)
    return rounded if rounded > floor else floor


def compute(assignment, variant, schedule):
    """Return the component figures for one variant of the pay formula."""
    hearing = db.hearings[assignment["hearing_id"]]
    language = db.languages[hearing["language_id"]]

    if variant == "LATE_CANCELLATION":
        billable = dec(schedule["late_cancellation_pay_hours"])
        miles = dec(0)
    else:
        if variant == "PROVISIONAL":
            start = parse_dt(hearing["scheduled_start"])
            end = parse_dt(hearing["scheduled_end"])
            miles = dec(assignment["estimated_one_way_miles"] or 0)
        else:
            start = parse_dt(assignment["check_in_utc"])
            end = parse_dt(assignment["actual_end_utc"])
            miles = dec(assignment["actual_one_way_miles"] or 0)
        billable = _billable_from_window(start, end, schedule["minimum_call_hours"])

    tier_rate = dec(schedule[TIER_RATE_FIELD[assignment["credential_tier_snapshot"]]])
    multiplier = (
        dec(1)
        if assignment["delivery_mode"] == "IN_PERSON"
        else dec(schedule["remote_rate_multiplier"])
    )
    service_cents = round_half_up_cents(billable * tier_rate * multiplier)

    if language["tier_class"] == "RARE":
        if service_cents >= schedule["rare_premium_bracket_cents"]:
            pct = dec(schedule["rare_premium_high_pct"])
        else:
            pct = dec(schedule["rare_premium_low_pct"])
        rare_premium_cents = round_half_up_cents(dec(service_cents) * pct)
    else:
        rare_premium_cents = 0

    if assignment["delivery_mode"] != "IN_PERSON" or miles <= dec(
        schedule["travel_free_radius_miles"]
    ):
        reimbursable = dec(0)
    else:
        reimbursable = dec(2) * miles
    travel_cents = round_half_up_cents(reimbursable * dec(schedule["travel_mileage_rate_cents"]))

    return {
        "billable_hours": hours_two_dp(billable),
        "service_cents": service_cents,
        "rare_premium_cents": rare_premium_cents,
        "travel_cents": travel_cents,
        "total_cents": service_cents + rare_premium_cents + travel_cents,
    }
