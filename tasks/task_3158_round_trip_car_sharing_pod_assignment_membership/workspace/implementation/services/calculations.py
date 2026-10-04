"""Every calculation rule from scaffold §1.3, implemented in the pinned order.

Money is never held in float: all monetary arithmetic runs through
``decimal.Decimal`` with round-half-up on a whole-cent quantum, per PRD §2.9.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, whole_minutes, parse_ts, ordered

# ---- C1 charge_with_late_penalty_and_fuel_adjustment ------------------------
HOURLY_RATE_CENTS = 1150
LAZY_MINUTES_PER_BLOCK = 30
GRACE_MINUTES = 10
LATE_MULTIPLIER = Decimal("1.5")
LATE_BLOCK_ESCALATION = Decimal("1.17")
ESCALATION_CAP_BLOCKS = 3
FUEL_SURCHARGE_CEILING = Decimal(450)
FUEL_SURCHARGE_STEP_PCT = Decimal(12)
FUEL_MISSING_LEVEL_FINE_CENTS = 2500
SURCHARGE_REDUCED_CENTS = 750
LONG_RESERVATION_DISCOUNT_PCT = Decimal("0.20")
LONG_RESERVATION_DISCOUNT_ALT_PCT = Decimal("0.15")
LONG_RESERVATION_DISCOUNT_ALT_THRESHOLD_CENTS = 100000

# ---- C2 late_return_penalty -------------------------------------------------
LATE_TIER_1_FEE_CENTS = 6000
LATE_TIER_2_FEE_CENTS = 8000

# ---- C3 damage_assessment ---------------------------------------------------
PLUS_DEDUCTIBLE_CENTS = 2000
PREMIUM_DEDUCTIBLE_CENTS = 3000
STANDARD_LIABILITY_PCT = Decimal("1.00")
PLUS_LIABILITY_PCT = Decimal("0.10")
PREMIUM_LIABILITY_PCT = Decimal("0.00")
ESTIMATE_PCT = Decimal("0.50")

# ---- C6 shift_bundle_fee ----------------------------------------------------
PER_POD_FEE_CENTS = 5000
BALANCED_TOLERANCE = 1
BALANCED_SURCHARGE_CENTS = 3200
MID_BALANCED_SURCHARGE_CENTS = 10400
IMBALANCED_SURCHARGE_CENTS = 19600
SOURCE_RETAINED_RATIO = 3

# ---- C8 strike_escalation ---------------------------------------------------
WEIGHTS = {"FUEL_LEVEL": 1, "CLEANLINESS": 2, "LOCKOUT": 3}
STRIKES_DIVISOR = 2
VIOLATION_FEE_CENTS = 1000

# ---- C9 damage_severity_score ----------------------------------------------
DAMAGE_SEVERITY_CENTS = 1500
DAMAGE_EXCESS_FLAT_CENTS = 1500
SEVERITY_HIGH_THRESHOLD = 4
SEVERITY_LOW_THRESHOLD = 2

# ---- C12 occupancy_fee_derivation_order ------------------------------------
MEMBERSHIP_DUES_CENTS = 7000
REGISTRATION_BASE_CENTS = 2500
REGISTRATION_FEE_REDUCTION_PCT = Decimal(20)
DISCOUNT_HIGH_PCT = Decimal("0.10")
DISCOUNT_HIGH_THRESHOLD_CENTS = 10000
DISCOUNT_LOW_PCT = Decimal("0.05")

# ---- C11 membership_thaw_and_residual_release ------------------------------
RESIDUAL_RELEASE_PCT = Decimal(80)


def _rh(value):
    """round_half_up to a whole cent."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _ru(value):
    """ceiling to a whole cent."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding="ROUND_CEILING"))


def ceil_div(a, b):
    return -(-int(a) // int(b))


def lateness_blocks(late_minutes):
    """Blocks are zero inside the 10-minute grace window, else ceil(minutes/30)."""
    if late_minutes <= GRACE_MINUTES:
        return 0
    return ceil_div(late_minutes, LAZY_MINUTES_PER_BLOCK)


def _block_raw_rate(block):
    """Raw (unrounded) rate for one 30-minute late block (PRD §3.9)."""
    if block == 0 or block > ESCALATION_CAP_BLOCKS:
        return Decimal(0)
    rate = Decimal(HOURLY_RATE_CENTS) * LATE_MULTIPLIER
    for _ in range(2, block + 1):
        rate = rate * LATE_BLOCK_ESCALATION
    return rate


def late_fee_cents(blocks):
    """Round EACH block then SUM: the rounding order is pinned (PRD §3.9)."""
    return sum(_rh(_block_raw_rate(b)) for b in range(1, blocks + 1))


def fuel_level_after_pct_to_level(pct):
    pct = int(pct)
    if 35 <= pct <= 100:
        return 1
    if 1 <= pct <= 34:
        return 2
    return 3


def fuel_deficit_pct(pod_floor, returned_fuel_pct):
    return max(0, int(pod_floor) - int(returned_fuel_pct))


def fuel_surcharge_cents(deficit_pct, bucket):
    if deficit_pct > 0:
        raw = (Decimal(deficit_pct) * FUEL_SURCHARGE_STEP_PCT / Decimal(100)) * FUEL_SURCHARGE_CEILING
        return _ru(raw)
    if bucket >= 3:
        return SURCHARGE_REDUCED_CENTS
    return 0


def fuel_level_fine_cents(bucket):
    return FUEL_MISSING_LEVEL_FINE_CENTS * max(0, bucket - 1)


def daily_rate_cents(reserved_hours):
    """The ordered daily-rate table, evaluated top-down with first match winning."""
    if reserved_hours is None or int(reserved_hours) == 0:
        return 6450
    hours = int(reserved_hours)
    if hours >= 120:
        return 4650
    if hours >= 72:
        return 5450
    if hours >= 24:
        return 6450
    return 7450


def time_component_cents(reservation, lateness):
    reserved_hours = int(reservation.get("reserved_hours") or 0)
    if reserved_hours <= 0:
        return daily_rate_cents(reserved_hours)
    billed_late_blocks = min(lateness, ESCALATION_CAP_BLOCKS)
    on_time_blocks = max(0, reserved_hours - billed_late_blocks)
    hourly = on_time_blocks * HOURLY_RATE_CENTS
    late = _rh(Decimal(billed_late_blocks) * Decimal(HOURLY_RATE_CENTS) * LATE_MULTIPLIER)
    return hourly + int(late)


def reservation_charge(reservation, vehicle, pod, returned_fuel_pct, now_iso=None):
    """The single charge written into Reservation.charge_total_cents (PRD §3.9).

    ``now_iso`` overrides the reference instant for a reservation still awaiting
    its physical return; PRD §3.9 pins the reference as "`returned_at` when that
    value is not null, and otherwise the reservation's `end_at`", and the lateness
    dimension of §3.10 measures that same reservation against the logical clock.
    """
    reference = reservation.get("returned_at") or now_iso or reservation.get("end_at")
    late_minutes = max(0, whole_minutes(reference, reservation["end_at"]))
    blocks = lateness_blocks(late_minutes)

    late_fee = late_fee_cents(blocks)
    time_component = time_component_cents(reservation, blocks)

    if returned_fuel_pct is None:
        returned_fuel_pct = vehicle.get("fuel_level_pct", 0)
    bucket = fuel_level_after_pct_to_level(returned_fuel_pct)
    from services.pods import fuel_floor
    deficit = fuel_deficit_pct(fuel_floor(pod), returned_fuel_pct)
    surcharge = fuel_surcharge_cents(deficit, bucket)
    fine = fuel_level_fine_cents(bucket)

    pre_discount = time_component + late_fee + surcharge + fine
    projected_vehicle_charge = int(vehicle.get("charge_total_cents") or 0) + pre_discount
    discount_pct = (LONG_RESERVATION_DISCOUNT_PCT
                    if projected_vehicle_charge < LONG_RESERVATION_DISCOUNT_ALT_THRESHOLD_CENTS
                    else LONG_RESERVATION_DISCOUNT_ALT_PCT)
    discount = int(Decimal(pre_discount) * discount_pct)  # floor of the product
    return pre_discount - discount, late_minutes


# ---- C2 late_return_penalty -------------------------------------------------
def _qualifying_transactions(vehicle_id):
    """POSTED fuel-card transactions for the vehicle, created_at ASC with the
    standard common-field fallback so ordering never depends on a random id."""
    rows = [t for t in STORE.fuel_transactions.values()
            if t.get("vehicle_id") == vehicle_id and t.get("status") == "POSTED"]
    return ordered(rows)


def last_txn_total_cents(txns, n):
    count = len(txns)
    take = min(n, count)
    if take <= 0:
        return 0
    return sum(int(t.get("amount_cents", 0)) for t in txns[count - take:])


def late_penalty_cents(reservation, vehicle, now_iso=None):
    reference = reservation.get("returned_at") or now_iso or reservation.get("end_at")
    late_minutes = max(0, whole_minutes(reference, reservation["end_at"]))
    blocks = lateness_blocks(late_minutes)
    s = max(0, blocks - ceil_div(GRACE_MINUTES, LAZY_MINUTES_PER_BLOCK))

    if s == 0:
        return 0
    if s == 1:
        return LATE_TIER_1_FEE_CENTS
    if s == 2:
        return LATE_TIER_2_FEE_CENTS
    txns = _qualifying_transactions(vehicle["id"])
    delta = last_txn_total_cents(txns, s - 3 + 1) - last_txn_total_cents(txns, s - 3)
    return LATE_TIER_2_FEE_CENTS + delta


# ---- C3 damage_assessment ---------------------------------------------------
def insurance_for_tier(tier):
    if tier == "PLUS":
        return PLUS_DEDUCTIBLE_CENTS, PLUS_LIABILITY_PCT
    if tier == "PREMIUM":
        return PREMIUM_DEDUCTIBLE_CENTS, PREMIUM_LIABILITY_PCT
    return 0, STANDARD_LIABILITY_PCT


def damage_estimate_cents(repair_cost_cents):
    """The tier-blind ESTIMATE variant (PRD §3.13)."""
    return _rh(Decimal(int(repair_cost_cents)) * ESTIMATE_PCT)


def damage_final_cents(repair_cost_cents, tier):
    """The FINAL variant written into Incident.member_damage_fee_cents.

    PRD §3.13 pins the documented outcomes: a STANDARD membership carries a zero
    deductible and a 1.00 liability fraction, so the member pays the whole repair
    cost; a PLUS membership with a repair cost of 30000 pays only 3000 cents
    "because the liability fraction of 0.10 gives 3000 and the deductible of 2000
    is waived against it"; and a PREMIUM membership has a 0.00 liability fraction
    and pays its 3000-cent deductible. The member fee is therefore the deductible
    and the liability share taken together, never less than either alone.
    """
    deductible, pct = insurance_for_tier(tier)
    insurance = _rh(Decimal(int(repair_cost_cents)) * pct)
    return max(deductible, insurance)


# ---- C6 shift_bundle_fee ----------------------------------------------------
def shift_bundle_fee(vehicle_count, source_available, dest_available):
    per_pod = PER_POD_FEE_CENTS * vehicle_count
    if vehicle_count == 0:
        surcharge = IMBALANCED_SURCHARGE_CENTS
    elif abs(source_available - dest_available) <= BALANCED_TOLERANCE:
        surcharge = BALANCED_SURCHARGE_CENTS
    elif min(source_available, dest_available) * SOURCE_RETAINED_RATIO >= max(source_available, dest_available):
        surcharge = MID_BALANCED_SURCHARGE_CENTS
    else:
        surcharge = IMBALANCED_SURCHARGE_CENTS
    return per_pod + surcharge


# ---- C8 strike_escalation ---------------------------------------------------
def strike_fee_cents(strikes):
    overage = max(0, strikes - 2)
    return VIOLATION_FEE_CENTS * overage


# ---- C9 damage_severity_score ----------------------------------------------
def severity_score(member, incident):
    t1 = int(member.get("last_accident_fee_block") or 0)
    t2 = 1 if int(member.get("strikes") or 0) == 0 else 2
    t3 = 1 if int(incident.get("repair_cost_cents") or 0) >= 10000 else 0
    return t1 + t2 + t3, t1


def severity_fee_high(raw_score, t1):
    excess = max(0, raw_score - t1)
    return DAMAGE_SEVERITY_CENTS * raw_score + DAMAGE_EXCESS_FLAT_CENTS * excess


def severity_fee_low(t1, t3):
    excess = max(0, t3 - 2)
    return DAMAGE_SEVERITY_CENTS * t1 + DAMAGE_EXCESS_FLAT_CENTS * excess


# ---- C12 occupancy_fee_derivation_order ------------------------------------
def membership_billing_cents():
    """Fee derived from the pre-fee dues; discount keyed on the post-fee total."""
    dues = Decimal(MEMBERSHIP_DUES_CENTS)
    registration_fee = Decimal(REGISTRATION_BASE_CENTS) * (
        Decimal(1) - REGISTRATION_FEE_REDUCTION_PCT / Decimal(100))
    total = dues + registration_fee
    pct = DISCOUNT_HIGH_PCT if total >= DISCOUNT_HIGH_THRESHOLD_CENTS else DISCOUNT_LOW_PCT
    discount = int(total * pct)  # floor of the product
    return int(total) - discount


# ---- C11 membership_thaw_and_residual_release ------------------------------
def residual_release_cents(membership_billing):
    return int(Decimal(int(membership_billing)) * RESIDUAL_RELEASE_PCT / Decimal(100))


# ---- C5 anchor helpers ------------------------------------------------------
def early_grade_window_hours():
    return 24