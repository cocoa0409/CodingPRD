"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 2.4, 2.8, 3.4-3.5).

All monetary arithmetic is integer cents; every percentage component is rounded
half up to a whole cent before any flat component is added.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- stay_ancillary_charge -------------------------------------------------
ELECTRIC_30A_PER_NIGHT_CENTS = 700
ELECTRIC_50A_PER_NIGHT_CENTS = 1200
ELECTRIC_50A_PER_NIGHT_CENTS_TRAILER = 900
ELECTRIC_PER_NIGHT_CEILING_CENTS = 1200
GUEST_PASS_PURCHASE_CENTS = 500
ANCILLARY_HARD_CAP_CENTS = 25000
TIER_DISCOUNT_PCT = {"CLASSIC": 0, "PLUS": 10, "PREMIER": 20}

# --- host_patronization_credit ---------------------------------------------
PATRONIZATION_RATE = Decimal("0.05")
PATRONIZATION_CAP_CENTS = 1500

# --- late_cancellation_fee -------------------------------------------------
FREE_CANCEL_DAYS = 7
TIER_LOW_MAX_CENTS = 2000
TIER_MID_MAX_CENTS = 5000
TIER_MID_PCT = Decimal("0.15")
TIER_MID_FLAT_CENTS = 500
TIER_HIGH_PCT = Decimal("0.25")
TIER_HIGH_FLAT_CENTS = 1500

# --- member_standing_score -------------------------------------------------
BASE_SCORE = 100
PENALTY = {"MINOR": -5, "MAJOR": -15, "SEVERE": -40}
STRIKE_SEVERITIES = ("MAJOR", "SEVERE")
STRIKE_REMOVAL_THRESHOLD = 3

# --- guest_pass_allotment --------------------------------------------------
GUEST_PASS_ALLOTMENT = {"CLASSIC": 0, "PLUS": 2, "PREMIER": 4}

# --- host_posture_derivation ----------------------------------------------
LIMITED_BAND_PCT = Decimal("0.20")

# --- ordinance_compliance --------------------------------------------------
ORDINANCE_RULE_SET = {
    ("OR", "WINERY"): {"max_sites": 2, "self_containment": True},
    ("OR", "FARM"): {"max_sites": 6, "self_containment": True},
    ("CA", "WINERY"): {"max_sites": 4, "self_containment": True},
    ("CA", "BREWERY"): {"max_sites": 3, "self_containment": False},
    ("TX", "FARM"): {"max_sites": 8, "self_containment": False},
    ("TX", "ATTRACTION"): {"max_sites": 10, "self_containment": False},
}

ELECTRIC_RANK = {"NONE": 0, "ELECTRIC_30A": 1, "ELECTRIC_50A": 2}
VEHICLE_CLASSES = (
    "CLASS_A",
    "CLASS_B",
    "CLASS_C",
    "FIFTH_WHEEL",
    "TRAVEL_TRAILER",
    "CONVERSION_VAN",
)

ACTIVE_STAY_STATUSES = ("CONFIRMED", "CHECKED_IN")
IN_FLIGHT_STAY_STATUSES = ("REQUESTED", "CONFIRMED", "CHECKED_IN")
WINDOW_ACTIVE_BASES = ("OPEN", "LIMITED")


def round_half_up(value):
    """Round a Decimal (or int/str) to a whole number, half up."""
    decimal_value = Decimal(str(value))
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(value):
    """Round to two decimals, half up, returned as a float for JSON output."""
    decimal_value = Decimal(str(value))
    return float(
        decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def electric_night_cents(electric_request_code, vehicle_class):
    """Step 1 of stay_ancillary_charge: the per-night electric rate."""
    if electric_request_code == "NONE" or electric_request_code is None:
        rate = 0
    elif electric_request_code == "ELECTRIC_30A":
        rate = ELECTRIC_30A_PER_NIGHT_CENTS
    elif electric_request_code == "ELECTRIC_50A":
        if vehicle_class in ("CLASS_A", "FIFTH_WHEEL"):
            rate = ELECTRIC_50A_PER_NIGHT_CENTS
        else:
            rate = ELECTRIC_50A_PER_NIGHT_CENTS_TRAILER
    else:
        rate = 0
    return min(rate, ELECTRIC_PER_NIGHT_CEILING_CENTS)


def ancillary_charge_cents(stay, vehicle, member):
    """stay_ancillary_charge, all four stages in their contractual order."""
    nights = stay.get("nights") or 0
    # Stage 1 -- electric, per night, then multiplied out.
    nightly = electric_night_cents(
        stay.get("electric_request_code", "NONE"), vehicle.get("vehicle_class")
    )
    electric_cents = nightly * nights
    # Stage 2 -- guest passes; the driver is never a guest.
    guests_beyond_driver = max(0, (stay.get("party_size") or 1) - 1)
    covered = member.get("guest_passes_remaining") or 0
    billable_guests = max(0, guests_beyond_driver - covered)
    guest_cents = GUEST_PASS_PURCHASE_CENTS * billable_guests
    # Stage 3 -- one discount on the whole subtotal.
    subtotal_cents = electric_cents + guest_cents
    pct = TIER_DISCOUNT_PCT.get(member.get("plan_tier"), 0)
    discount_cents = round_half_up(Decimal(subtotal_cents) * pct / Decimal(100))
    # Stage 4 -- clamp: floored at zero, then capped at 25000 cents.
    charged = subtotal_cents - discount_cents
    return min(max(0, charged), ANCILLARY_HARD_CAP_CENTS)


def late_cancellation_fee_cents(days_before_arrival, ancillary_cents):
    """late_cancellation_fee: bands on notice first, then on the ancillary."""
    ancillary_cents = ancillary_cents or 0
    if days_before_arrival >= FREE_CANCEL_DAYS:
        return 0
    if ancillary_cents <= TIER_LOW_MAX_CENTS:
        return 0
    if ancillary_cents <= TIER_MID_MAX_CENTS:
        pct_part = round_half_up(Decimal(ancillary_cents) * TIER_MID_PCT)
        return pct_part + TIER_MID_FLAT_CENTS
    pct_part = round_half_up(Decimal(ancillary_cents) * TIER_HIGH_PCT)
    return pct_part + TIER_HIGH_FLAT_CENTS


def host_patronization_credit_cents(receipt_cents):
    """Per-record credit: rounded before capping, capped per record."""
    credit = round_half_up(Decimal(receipt_cents) * PATRONIZATION_RATE)
    return min(credit, PATRONIZATION_CAP_CENTS)


def standing_score(incidents):
    total = BASE_SCORE
    for incident in incidents:
        if incident.get("incident_status") == "WITHDRAWN":
            continue
        total += PENALTY.get(incident.get("severity"), 0)
    return max(0, total)


def strike_count(incidents):
    return sum(
        1
        for incident in incidents
        if incident.get("incident_status") != "WITHDRAWN"
        and incident.get("severity") in STRIKE_SEVERITIES
    )


def rating_average(ratings):
    """Mean of the published ratings, half up to two decimals; 0.00 when empty."""
    if not ratings:
        return 0.00
    total = Decimal(sum(ratings))
    return round2(total / Decimal(len(ratings)))


def guest_pass_allotment(plan_tier):
    return GUEST_PASS_ALLOTMENT.get(plan_tier, 0)


def limited_band(effective_capacity):
    """ceil(effective_capacity * 0.20)."""
    exact = Decimal(int(effective_capacity)) * LIMITED_BAND_PCT
    return int(math.ceil(exact))


def ordinance_rule(state_code, category):
    return ORDINANCE_RULE_SET.get((state_code, category))


def ordinance_violation(host, base_capacity):
    """ordinance_compliance: cap on physical sites plus forced self-containment."""
    rule = ordinance_rule(host.get("state_code"), host.get("category"))
    if rule is None:
        return False
    if rule["self_containment"] and host.get("self_contained_required") is False:
        return True
    return base_capacity > rule["max_sites"]