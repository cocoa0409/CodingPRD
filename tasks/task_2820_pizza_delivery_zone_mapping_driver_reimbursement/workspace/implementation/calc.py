"""The eleven calculations of PRD 3, in integer cents / micro-degrees /
two-decimal miles / whole minutes, with the rounding placed exactly where the
specification places it (PRD 2.6)."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

MICRO_PER_MILE = Decimal(15000)
TWO = Decimal("0.01")

FEE_TIER_SURCHARGE_CENTS = {"BASE": 0, "MID": 150, "FAR": 350}
PEAK_HOURS_UTC = (17, 18, 19, 20)
INSURANCE_MIN_LIMIT_CENTS = 10000000


def q2(value):
    """Round half up to exactly two decimal places."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a fractional monetary intermediate half up to a whole cent."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_minutes(value):
    """Round a fractional minute UP to the next whole minute."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def miles_out(value):
    """Render a two-decimal mileage for JSON."""
    if value is None:
        return None
    return float(q2(value))


# --- 1. grid_distance_miles ---------------------------------------------------

def grid_miles(store, latitude_micro, longitude_micro):
    delta = abs(latitude_micro - store["latitude_micro"]) + abs(
        longitude_micro - store["longitude_micro"]
    )
    return q2(Decimal(delta) / MICRO_PER_MILE)


# --- 2. drive_time_estimate --------------------------------------------------

def drive_time_estimate(zone_version, miles, crosses_barrier, now):
    mileage_term = ceil_minutes(Decimal(miles) * zone_version["minutes_per_mile"])
    peak = zone_version["peak_surcharge_minutes"] if now.hour in PEAK_HOURS_UTC else 0
    barrier = zone_version["barrier_surcharge_minutes"] if crosses_barrier else 0
    return zone_version["base_drive_minutes"] + mileage_term + max(peak, barrier)


# --- 3. zone_state_classification --------------------------------------------

def point_inside_ring(ring, latitude_micro, longitude_micro):
    """Integer ray casting. A point exactly on an edge counts as INSIDE."""
    px = longitude_micro
    py = latitude_micro
    count = len(ring)
    inside = False
    for index in range(count):
        a = ring[index]
        b = ring[(index + 1) % count]
        ax = a["longitude_micro"]
        ay = a["latitude_micro"]
        bx = b["longitude_micro"]
        by = b["latitude_micro"]
        # On-edge test: collinear and within the rectangle the endpoints bound.
        if (bx - ax) * (py - ay) - (by - ay) * (px - ax) == 0:
            if min(ax, bx) <= px <= max(ax, bx) and min(ay, by) <= py <= max(ay, by):
                return True
        # An edge participates only when exactly one endpoint is strictly above.
        if (ay > py) != (by > py):
            first = (px - ax) * (by - ay)
            second = (bx - ax) * (py - ay)
            if by > ay:
                if first < second:
                    inside = not inside
            else:
                if first > second:
                    inside = not inside
    return inside


def zone_state(zone_version, latitude_micro, longitude_micro, drive_minutes):
    if not point_inside_ring(zone_version["polygon"], latitude_micro, longitude_micro):
        return "OUT_OF_ZONE"
    if drive_minutes <= zone_version["max_drive_time_minutes"]:
        return "IN_ZONE"
    return "EDGE"


# --- 4. customer_delivery_charge ---------------------------------------------

def fee_tier(drive_minutes):
    if drive_minutes <= 15:
        return "BASE"
    if drive_minutes <= 25:
        return "MID"
    return "FAR"


def fee_waiver_pct(food_subtotal_cents):
    if food_subtotal_cents >= 3000:
        return 100
    if food_subtotal_cents >= 2000:
        return 50
    return 0


def price_order(store, drive_minutes, food_subtotal_cents, tip_cents):
    tier = fee_tier(drive_minutes)
    base = store["delivery_fee_cents"] + FEE_TIER_SURCHARGE_CENTS[tier]
    waiver = fee_waiver_pct(food_subtotal_cents)
    charged = cents(Decimal(base) * Decimal(100 - waiver) / Decimal(100))
    return {
        "fee_tier": tier,
        "base_delivery_fee_cents": base,
        "fee_waiver_pct": waiver,
        "delivery_fee_cents": charged,
        "total_charge_cents": food_subtotal_cents + charged + tip_cents,
    }


# --- 6. route_duration_model -------------------------------------------------

def route_minutes(leg_minutes, handoff_minutes_per_stop):
    """leg_minutes is the per-stop outbound leg, in sequence ascending order."""
    if not leg_minutes:
        return 0
    outbound = sum(leg_minutes)
    handoff = handoff_minutes_per_stop * len(leg_minutes)
    homeward = leg_minutes[-1]
    return outbound + handoff + homeward


# --- 7. dispatch_reimbursement (the cumulative two-tier waterfall) -----------

def waterfall(stop_miles, model):
    """Returns (total_cents, [per-stop cents]) for stop mileages in sequence order."""
    cap = Decimal(str(model["tier1_cap_miles"]))
    tier1_rate = Decimal(model["tier1_per_mile_cents"])
    tier2_rate = Decimal(model["tier2_per_mile_cents"])
    per_delivery = Decimal(model["per_delivery_cents"])
    floor_cents = model["min_reimbursement_per_stop_cents"]
    cumulative = Decimal(0)
    total = 0
    per_stop = []
    for raw_miles in stop_miles:
        miles = Decimal(str(raw_miles if raw_miles is not None else 0))
        room = cap - cumulative
        if room < 0:
            room = Decimal(0)
        tier1 = miles if miles < room else room
        tier2 = miles - tier1
        raw = tier1 * tier1_rate + tier2 * tier2_rate + per_delivery
        amount = cents(raw)
        if amount < floor_cents:
            amount = floor_cents
        per_stop.append(amount)
        total += amount
        cumulative += miles
    return total, per_stop


# --- 8. order_to_door_minutes ------------------------------------------------

def order_to_door(gross_minutes, zone_hold_minutes, remake_hold_minutes):
    net = gross_minutes - zone_hold_minutes - remake_hold_minutes
    if net < 0:
        net = 0
    return gross_minutes, net


# --- 9. complaint_remedy -----------------------------------------------------

def complaint_remedy(category, order):
    food = order["food_subtotal_cents"]
    if category == "LATE":
        gross = order.get("order_to_door_gross_minutes")
        overage = (gross if gross is not None else 0) - order["promise_minutes_snapshot"]
        if overage >= 20:
            pct = 100
            fee_refund = order["delivery_fee_cents"]
        elif overage >= 10:
            pct = 50
            fee_refund = 0
        elif overage >= 1:
            pct = 20
            fee_refund = 0
        else:
            pct = 0
            fee_refund = 0
        raw = cents(Decimal(food) * Decimal(pct) / Decimal(100)) + fee_refund
        basis = "LATE_TIER"
    elif category == "FEE_DISCLOSURE":
        penalty = 0 if order.get("fee_disclosure_accurate") else 500
        raw = order["delivery_fee_cents"] + penalty
        basis = "FEE_REFUND"
    elif category == "QUALITY":
        raw = cents(Decimal(food) * Decimal(50) / Decimal(100))
        basis = "QUALITY_HALF"
    else:
        raw = 0
        basis = "CONDUCT_ZERO"
    capped = raw if raw < order["total_charge_cents"] else order["total_charge_cents"]
    return capped, basis
