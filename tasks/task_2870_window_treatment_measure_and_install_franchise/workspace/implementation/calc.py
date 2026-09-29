"""Every calculation the PRD declares, with its exact constants and rounding."""

from datetime import timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from core import money, store, LIVE_ORDER_STATUSES

# --- geometry -------------------------------------------------------------
INSIDE_WIDTH_DEDUCTION_IN = Decimal("0.500")
INSIDE_HEIGHT_DEDUCTION_IN = Decimal("0.250")
OUTSIDE_WIDTH_OVERLAP_IN = Decimal("1.500")
OUTSIDE_HEIGHT_HEADER_IN = Decimal("3.000")
OUTSIDE_HEIGHT_SILL_OVERLAP_IN = Decimal("1.500")
EIGHTH = Decimal("0.125")
THREE_DP = Decimal("0.001")

# --- pricing --------------------------------------------------------------
MIN_BILLABLE_WIDTH_IN = Decimal("12.000")
MIN_BILLABLE_HEIGHT_IN = Decimal("12.000")
OVERSIZE_WIDTH_IN = Decimal("72.000")
OVERSIZE_SURCHARGE_PCT = Decimal("0.15")
FABRIC_RATE_CENTS_PER_SQFT = {
    "LT-SHEER": 620, "CL-LINEN": 940, "BO-THERMAL": 1280, "WD-FAUX": 1550,
}
LIFT_UPLIFT_CENTS = {
    "CORDED": 0, "CORDLESS": 1800, "CONTINUOUS_LOOP": 2600, "MOTORIZED": 0,
}
MOTOR_PRICE_CENTS = {"NONE": 0, "BATTERY": 12500, "HARDWIRED": 19500}

# --- quote ----------------------------------------------------------------
INSTALL_BASE_FEE_CENTS = 7500
INSTALL_PER_OPENING_CENTS = 2500
MOTOR_COMMISSIONING_FEE_CENTS = 4500
DISCOUNT_TIERS = ((500000, Decimal("0.12")), (250000, Decimal("0.08")),
                  (100000, Decimal("0.05")))
QUOTE_VALIDITY_DAYS = 14
QUOTE_MAX_REVISIONS = 2

# --- vendor ---------------------------------------------------------------
VENDOR_COST_PCT = Decimal("0.42")
REMAKE_EXPEDITE_DAYS = 4
MIN_LEAD_TIME_DAYS = 5
REMAKE_TERRITORY_CAP_CENTS = 15000
ORDER_MAX_REMAKES = 2
VENDOR_REMAKE_WINDOW_DAYS = 90

# --- samples --------------------------------------------------------------
SAMPLE_LATE_FEE_PER_DAY_CENTS = 750
SAMPLE_LOST_THRESHOLD_DAYS = 14
SAMPLE_MAX_HOLD_DAYS = 14

# --- measurement / liability ---------------------------------------------
OUT_OF_SQUARE_TOLERANCE_IN = Decimal("0.375")
MIN_INSIDE_DEPTH_IN = Decimal("2.500")
REMEASURE_CHARGE_PCT = Decimal("0.35")
REMEASURE_CHARGE_CAP_CENTS = 12000
COMMISSIONING_MAX_ATTEMPTS = 3

ROOM_TYPES = ("BEDROOM", "NURSERY", "LIVING_ROOM", "KITCHEN", "BATH", "OFFICE")
MOUNT_TYPES = ("INSIDE", "OUTSIDE")
FABRIC_CODES = tuple(FABRIC_RATE_CENTS_PER_SQFT.keys())
LIFT_SYSTEMS = tuple(LIFT_UPLIFT_CENTS.keys())
MOTOR_OPTIONS = tuple(MOTOR_PRICE_CENTS.keys())
CERTIFICATIONS = ("MOTORIZATION", "CHILD_SAFETY", "COMMERCIAL")
HUB_PLATFORMS = ("ALEXA", "GOOGLE_HOME", "HOMEKIT", "MATTER")
CHILD_SAFE_LIFTS = ("CORDLESS", "MOTORIZED")
CHILD_SAFE_ROOMS = ("NURSERY", "BEDROOM")


def _floor_eighth(value):
    return (value * 8).to_integral_value(rounding=ROUND_FLOOR) * EIGHTH


def _ceil_eighth(value):
    return (value * 8).to_integral_value(rounding=ROUND_CEILING) * EIGHTH


def ordered_dimensions(mount_type, widths, heights):
    """PRD 3.4: six wall readings to out-of-square plus ordered dimensions."""
    narrowest = min(widths)
    widest = max(widths)
    shortest = min(heights)
    tallest = max(heights)
    spread = max(widest - narrowest, tallest - shortest)
    out_of_square = spread.quantize(THREE_DP, rounding=ROUND_HALF_UP)
    if mount_type == "INSIDE":
        width = _floor_eighth(narrowest - INSIDE_WIDTH_DEDUCTION_IN)
        height = _floor_eighth(shortest - INSIDE_HEIGHT_DEDUCTION_IN)
    else:
        width = _ceil_eighth(widest + OUTSIDE_WIDTH_OVERLAP_IN * 2)
        height = _ceil_eighth(
            tallest + OUTSIDE_HEIGHT_HEADER_IN + OUTSIDE_HEIGHT_SILL_OVERLAP_IN)
    return (out_of_square,
            width.quantize(THREE_DP),
            height.quantize(THREE_DP))


def billable_sqft(ordered_width, ordered_height):
    """PRD 3.5: quarter-square-foot billing unit, rounded up, per opening."""
    width = max(ordered_width, MIN_BILLABLE_WIDTH_IN)
    height = max(ordered_height, MIN_BILLABLE_HEIGHT_IN)
    scaled = int((width * height * Decimal(10) ** 6).to_integral_value(
        rounding=ROUND_HALF_UP))
    quarters = -(-scaled // 36000000)
    return width, height, (Decimal(quarters) / 4).quantize(Decimal("0.01"))


def price_opening(ordered_width, ordered_height, fabric_code, lift_system,
                  motorization_option):
    """PRD 3.5: exactly two rounding steps -- fabric charge, then surcharge."""
    width, _height, sqft = billable_sqft(ordered_width, ordered_height)
    fabric_cents = money(sqft * Decimal(FABRIC_RATE_CENTS_PER_SQFT[fabric_code]))
    combined = (fabric_cents
                + LIFT_UPLIFT_CENTS[lift_system]
                + MOTOR_PRICE_CENTS[motorization_option or "NONE"])
    rate = OVERSIZE_SURCHARGE_PCT if width > OVERSIZE_WIDTH_IN else Decimal("0")
    surcharge = money(Decimal(combined) * rate)
    return sqft, combined + surcharge


def discount_pct_for(pre_discount_total_cents):
    for threshold, pct in DISCOUNT_TIERS:
        if pre_discount_total_cents >= threshold:
            return pct
    return Decimal("0")


def quote_waterfall(openings):
    """PRD 3.6: the six-step waterfall, in exactly this order, once each."""
    opening_count = len(openings)
    motorized_count = len([o for o in openings
                           if (o.get("motorization_option") or "NONE") != "NONE"])
    subtotal = sum(o["list_price_cents"] for o in openings)
    install_fee = (INSTALL_BASE_FEE_CENTS
                   + INSTALL_PER_OPENING_CENTS * opening_count
                   + MOTOR_COMMISSIONING_FEE_CENTS * motorized_count)
    pre_discount_total = subtotal + install_fee
    pct = discount_pct_for(pre_discount_total)
    discount = money(Decimal(subtotal) * pct)
    total = pre_discount_total - discount
    net_sales = subtotal - discount
    return {
        "opening_count": opening_count,
        "motorized_opening_count": motorized_count,
        "subtotal_cents": subtotal,
        "install_fee_cents": install_fee,
        "pre_discount_total_cents": pre_discount_total,
        "discount_pct": pct,
        "discount_cents": discount,
        "total_cents": total,
        "net_sales_cents": net_sales,
    }


def cordless_required(opening, lead):
    if lead is not None and lead.get("child_occupied_dwelling"):
        return True
    return opening["room_type"] in CHILD_SAFE_ROOMS


def cordless_violated(openings, lead):
    for opening in openings:
        if cordless_required(opening, lead):
            if opening.get("lift_system") not in CHILD_SAFE_LIFTS:
                return True
    return False


def order_cost_cents(openings):
    """PRD 3.7: 42 percent of the summed retail, rounded once."""
    retail = sum(o["list_price_cents"] for o in openings)
    return money(Decimal(retail) * VENDOR_COST_PCT)


def compute_lead_time(vendor, placement_instant, motorized, remake_count):
    """PRD 3.7: cutoff roll, adders, expedite then floor, promised date."""
    moment = placement_instant.astimezone(timezone.utc)
    effective = moment.date()
    if moment.hour >= vendor["cutoff_hour_utc"]:
        effective = effective + timedelta(days=1)
    raw_days = vendor["base_lead_time_days"]
    if motorized:
        raw_days += vendor["motorization_extra_days"]
    if remake_count > 0:
        raw_days -= REMAKE_EXPEDITE_DAYS
    lead_time_days = max(raw_days, MIN_LEAD_TIME_DAYS)
    promised = effective + timedelta(days=lead_time_days)
    return effective, lead_time_days, promised


def capacity_admits(vendor, effective, promised, exclude_order_id=None):
    """PRD 3.7: a headcount on every single calendar date of the window."""
    occupying = []
    for order in store.vendor_orders.values():
        if order["vendor_id"] != vendor["id"]:
            continue
        if order["status"] not in LIVE_ORDER_STATUSES:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["effective_placement_date"] is None or order["promised_ship_date"] is None:
            continue
        occupying.append((order["effective_placement_date"], order["promised_ship_date"]))
    day = effective
    while day <= promised:
        load = len([1 for start, end in occupying if start <= day <= end])
        if load + 1 > vendor["concurrent_capacity"]:
            return False
        day = day + timedelta(days=1)
    return True


def remake_waterfall(remake_cost_cents, origin, vendor, liable_party=None):
    """PRD 3.8: three buckets filled strictly in order."""
    cost = int(remake_cost_cents)
    if origin == "INSTALL_EXCEPTION":
        if liable_party == "VENDOR":
            vendor_target, territory_target = cost, 0
        elif liable_party == "MEASURER":
            vendor_target, territory_target = 0, cost
        else:
            vendor_target, territory_target = 0, 0
    else:
        policy = vendor["remake_policy"]
        if policy == "FULL_VENDOR_90D":
            vendor_target, territory_target = cost, 0
        elif policy == "SHARED_50_50":
            vendor_target = cost // 2
            territory_target = cost - vendor_target
        else:
            vendor_target, territory_target = 0, 0
    vendor_absorbed = min(vendor_target, cost)
    territory_absorbed = min(territory_target, REMAKE_TERRITORY_CAP_CENTS,
                             cost - vendor_absorbed)
    customer_absorbed = cost - vendor_absorbed - territory_absorbed
    return vendor_absorbed, territory_absorbed, customer_absorbed


def remeasure_charge_cents(list_price_cents):
    """PRD 3.9: round half up first, cap afterwards."""
    charge = money(Decimal(int(list_price_cents)) * REMEASURE_CHARGE_PCT)
    return min(charge, REMEASURE_CHARGE_CAP_CENTS)


def days_late_for(returned_at, due_at):
    if returned_at <= due_at:
        return 0
    delta = returned_at - due_at
    micros = delta.days * 86400000000 + delta.seconds * 1000000 + delta.microseconds
    return -(-micros // 86400000000)


def sample_late_fee_cents(days_late, replacement_value_cents):
    return min(SAMPLE_LATE_FEE_PER_DAY_CENTS * days_late, replacement_value_cents)


def liable_party_for(reason, opening):
    """PRD 3.9: liability from the reason plus three stored facts."""
    if reason == "DAMAGED_GOODS":
        return "VENDOR"
    inside = opening["mount_type"] == "INSIDE"
    if reason == "OUT_OF_SQUARE":
        if inside and opening["out_of_square_in"] > OUT_OF_SQUARE_TOLERANCE_IN:
            return "MEASURER"
        return "CUSTOMER"
    if reason == "OBSTRUCTION":
        if inside and opening["depth_in"] >= MIN_INSIDE_DEPTH_IN:
            return "MEASURER"
        return "CUSTOMER"
    return "CUSTOMER"
