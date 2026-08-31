"""Measurement precision (PRD §2.6) and the eight calculation rules (§1.3)."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

ZERO = Decimal("0")

# calculations.event_slot_capacity
VEHICLES_PER_LANE_HOUR = Decimal("12")
STAFF_HOURS_PER_VEHICLE = Decimal("0.25")
CONTAINMENT_LITERS_PER_VEHICLE = Decimal("40")
REMEDIATED_DERATE = Decimal("0.5")

# calculations.program_posture
DEFICIENCY_FREEZE_COUNT = 2
RESTRICT_UTILIZATION_PCT = 85

# calculations.program_cost_rollup
CONTINGENCY_PCT = Decimal("0.08")
TIER_1_TONNAGE_KG = Decimal("2000")
TIER_2_TONNAGE_KG = Decimal("8000")
TIER_1_MOBILIZATION_CENTS = 250000
TIER_2_MOBILIZATION_CENTS = 180000
TIER_3_MOBILIZATION_CENTS = 120000
TIER_1_REBATE_PCT = Decimal("0.00")
TIER_2_REBATE_PCT = Decimal("0.03")
TIER_3_REBATE_PCT = Decimal("0.06")

# Site containment screen (PRD §3.2)
MIN_SECONDARY_CONTAINMENT_LITERS = 2000
MIN_STORM_DRAIN_DISTANCE_M = Decimal("15.0")

# Resident automatic suspension (PRD §3.7)
NO_SHOW_SUSPEND_THRESHOLD = 2

# Site scheduling geometry (PRD §3.3)
SITE_BUFFER_SECONDS = 48 * 3600
SITE_MONTHLY_EVENT_CAP = 2

# Staffer decontamination buffer (PRD §3.4)
DECON_BUFFER_SECONDS = 30 * 60
MAX_SHIFT_HOURS = Decimal("12.0")

# Appointment slot geometry (PRD §3.5)
SLOT_ALIGNMENT_SECONDS = 15 * 60


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


def cents(value):
    """round_half_up to a whole number of cents."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    return float(dec(value))


def hours_between(start_dt, end_dt):
    """Elapsed hours rounded half up to two decimal places."""
    seconds = Decimal(str((end_dt - start_dt).total_seconds()))
    return q2(seconds / Decimal("3600"))


# ------------------------------------------------- calculations.event_slot_capacity

def slot_capacity(open_lane_count, certified_staff_hours, window_duration_hours,
                  secondary_containment_liters, containment_status):
    lane_throughput = floor_int(
        dec(open_lane_count) * VEHICLES_PER_LANE_HOUR * dec(window_duration_hours))
    staffing_capacity = floor_int(dec(certified_staff_hours) / STAFF_HOURS_PER_VEHICLE)
    base_containment = floor_int(
        dec(secondary_containment_liters) / CONTAINMENT_LITERS_PER_VEHICLE)
    if containment_status == "COMPLIANT":
        containment_capacity = base_containment
    elif containment_status == "REMEDIATED":
        containment_capacity = floor_int(dec(base_containment) * REMEDIATED_DERATE)
    else:
        containment_capacity = 0
    return min(lane_throughput, staffing_capacity, containment_capacity)


# ------------------------------------------------ calculations.program_cost_rollup

def volume_tier(received_tonnage_kg):
    tonnage = dec(received_tonnage_kg)
    if tonnage < TIER_1_TONNAGE_KG:
        return TIER_1_MOBILIZATION_CENTS, TIER_1_REBATE_PCT
    if tonnage < TIER_2_TONNAGE_KG:
        return TIER_2_MOBILIZATION_CENTS, TIER_2_REBATE_PCT
    return TIER_3_MOBILIZATION_CENTS, TIER_3_REBATE_PCT
