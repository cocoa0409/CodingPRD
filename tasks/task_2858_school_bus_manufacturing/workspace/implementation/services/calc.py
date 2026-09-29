"""Calculation rules (PRD 3.2, 3.3, 3.5, 3.6, 3.7, 3.9).

Money is integer cents computed through decimal.Decimal with ROUND_HALF_UP at
exactly the points the rules name.  Range figures are floored / truncated.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_FLOOR

# ------------------------------------------------------------------ constants

DEALER_PREP_PCT = Decimal("0.02375")
SEAT_ADD_CENTS_EACH = 34500
EIGHT_LAMP_SYSTEM_CENTS = 148000
CROSSING_ARM_CENTS = 96500
MIRROR_SURCHARGE_CENTS = {"STANDARD": 0, "CROSSVIEW": 57400, "CROSSVIEW_HEATED": 83275}
LAP_SHOULDER_BELT_CENTS_PER_SEAT = 21750
EMERGENCY_EXIT_CENTS_EACH = 68000
ROLLOVER_REINFORCEMENT_CENTS = 213000
ROLLOVER_JOINT_BONUS_KN = Decimal("9.5")
ESCALATION_PCT_PER_MONTH = Decimal("0.0045")

COMPLIANCE_ADMIN_PCT = Decimal("0.0125")

AVG_ROUTE_SPEED_MPH = Decimal("20.0")
TERRAIN_FACTOR = {
    "FLAT": Decimal("1.00"),
    "ROLLING": Decimal("1.08"),
    "MOUNTAIN": Decimal("1.18"),
}

MIRROR_RANK = {"STANDARD": 0, "CROSSVIEW": 1, "CROSSVIEW_HEATED": 2}
MIRROR_BY_RANK = {0: "STANDARD", 1: "CROSSVIEW", 2: "CROSSVIEW_HEATED"}

REPLAN_LEAD_DAYS = 45
FINISH_LEAD_DAYS = 21
LD_CENTS_PER_UNIT_PER_DAY = 7500
LD_CAP_PCT = Decimal("0.05")

DEALER_RESTRICT_THRESHOLD = 2
DEALER_SUSPEND_THRESHOLD = 4
FACTORY_ESCALATION_EXTRA_KITS = 1

ROLLOVER_KN_PER_LB = Decimal("0.0025")
MAX_REVISION_ROUNDS = 3

BODY_CLASSES = ("TYPE_A", "TYPE_C", "TYPE_D")
PROPULSION_TYPES = ("DIESEL", "PROPANE", "ELECTRIC")
MIRROR_CONFIGS = ("STANDARD", "CROSSVIEW", "CROSSVIEW_HEATED")
TERRAIN_CLASSES = ("FLAT", "ROLLING", "MOUNTAIN")
TEST_TYPES = ("BRAKE", "EMERGENCY_EXIT", "ELECTRICAL", "JOINT_STRENGTH", "ROLLOVER")
DEFECT_CATEGORIES = (
    "BRAKE_LINE_CORROSION",
    "EMERGENCY_EXIT_LATCH",
    "WIRING_HARNESS",
    "BATTERY_CONTACTOR",
)
BUYER_TYPES = ("DISTRICT", "COOPERATIVE")


# -------------------------------------------------------------------- helpers

def dec(value):
    """Exact Decimal from an int / float / Decimal without binary noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(repr(float(value)))


def round_half_up(value, places=0):
    q = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def trunc_1dp(value):
    """Truncate toward zero to exactly one fractional digit."""
    return dec(value).quantize(Decimal("0.1"), rounding=ROUND_DOWN)


def as_number(value):
    """Emit a Decimal as a JSON number."""
    return float(value)


# --------------------------------------------------------------- bid_unit_price

def line_items(model, package, cfg):
    """The six ordered line items, in integer cents."""
    seats = int(cfg["seat_capacity"])
    exits = int(cfg["emergency_exit_count"])
    l1 = int(model["base_price_cents"])
    l2 = int(package["option_price_cents"])
    l3 = SEAT_ADD_CENTS_EACH * max(0, seats - int(model["base_seat_capacity"]))
    l4 = (EIGHT_LAMP_SYSTEM_CENTS if cfg["eight_lamp_system"] else 0) + (
        CROSSING_ARM_CENTS if cfg["crossing_arm"] else 0
    )
    l5 = MIRROR_SURCHARGE_CENTS[cfg["mirror_config"]]
    l6 = (
        (LAP_SHOULDER_BELT_CENTS_PER_SEAT * seats if cfg["lap_shoulder_belts"] else 0)
        + EMERGENCY_EXIT_CENTS_EACH * max(0, exits - int(model["base_emergency_exit_count"]))
        + (ROLLOVER_REINFORCEMENT_CENTS if cfg["rollover_reinforcement"] else 0)
    )
    return [l1, l2, l3, l4, l5, l6]


def unit_price_cents(model, package, cfg):
    """Provisional / upgraded unit price: prep fee rounded once per line item."""
    items = line_items(model, package, cfg)
    preps = [cents(dec(item) * DEALER_PREP_PCT) for item in items]
    return sum(items) + sum(preps)


def escalated_price(base_price, months):
    factor = Decimal(1) + ESCALATION_PCT_PER_MONTH * Decimal(int(months))
    return cents(dec(base_price) * factor)


def joint_strength_kn(model, rollover):
    value = dec(model["body_joint_strength_kn"])
    if rollover:
        value = value + ROLLOVER_JOINT_BONUS_KN
    return as_number(value)


def upgrade_config(cfg, profile):
    """Award-time / legacy-import spec upgrade: raise, never lower."""
    rank = max(MIRROR_RANK[cfg["mirror_config"]], MIRROR_RANK[profile["required_mirror_config"]])
    return {
        "seat_capacity": max(int(cfg["seat_capacity"]), int(profile["min_seat_capacity"])),
        "emergency_exit_count": max(
            int(cfg["emergency_exit_count"]), int(profile["min_emergency_exit_count"])
        ),
        "mirror_config": MIRROR_BY_RANK[rank],
        "lap_shoulder_belts": bool(cfg["lap_shoulder_belts"]) or bool(profile["requires_lap_shoulder_belts"]),
        "eight_lamp_system": bool(cfg["eight_lamp_system"]) or bool(profile["requires_eight_lamp_system"]),
        "crossing_arm": bool(cfg["crossing_arm"]) or bool(profile["requires_crossing_arm"]),
        "rollover_reinforcement": bool(cfg["rollover_reinforcement"])
        or bool(profile["requires_rollover_protection"]),
    }


# --------------------------------------------------------------- contract_total

def volume_discount_pct(unit_count):
    n = int(unit_count)
    if n >= 50:
        return Decimal("0.05")
    if n >= 25:
        return Decimal("0.035")
    if n >= 10:
        return Decimal("0.02")
    return Decimal("0.00")


def freight_fee_cents(discounted_subtotal):
    if discounted_subtotal < 50000000:
        return 1250000
    if discounted_subtotal < 150000000:
        return 2100000
    return 2950000


def contract_total_cents(awarded_unit_price, unit_count):
    subtotal = int(awarded_unit_price) * int(unit_count)
    discount = cents(dec(subtotal) * volume_discount_pct(unit_count))
    discounted_subtotal = subtotal - discount
    freight = freight_fee_cents(discounted_subtotal)
    admin = cents(dec(discounted_subtotal + freight) * COMPLIANCE_ADMIN_PCT)
    return discounted_subtotal + freight + admin


# ------------------------------------------------------------- range_validation

def range_validation(package, profile):
    """Return (nominal_range_mi as int, derated_route_range_mi as 1dp number)."""
    terrain = TERRAIN_FACTOR[profile["terrain_class"]]
    if package["propulsion_type"] == "ELECTRIC":
        usable = dec(package["usable_kwh"])
        consumption = dec(package["nominal_consumption_kwh_per_mi"])
        hvac = dec(package["hvac_load_kw"])
        reserve = dec(package["reserve_floor_pct"])
        cold = dec(package["cold_weather_derate_pct"])
        nominal = floor_int(usable / consumption) if consumption > 0 else 0
        effective = consumption + (hvac / AVG_ROUTE_SPEED_MPH)
        available = usable * (Decimal(1) - reserve) * (Decimal(1) - cold)
        if effective > 0 and terrain > 0:
            derated = trunc_1dp(available / effective / terrain)
        else:
            derated = trunc_1dp(Decimal(0))
        return nominal, as_number(derated)
    gallons = dec(package["fuel_capacity_gal"])
    mpg = dec(package["rated_mpg"])
    reserve = dec(package["reserve_floor_pct"])
    cold = dec(package["cold_weather_derate_pct"])
    nominal = floor_int(gallons * mpg)
    derated = trunc_1dp(
        gallons * (Decimal(1) - reserve) * mpg * (Decimal(1) - cold) / terrain
    )
    return nominal, as_number(derated)


# ---------------------------------------------------- spec_compliance_evaluation

MANDATORY_ITEMS = ("joint_strength", "rollover_protection", "route_range", "emergency_exits")
EXCEPTABLE_ITEMS = (
    "seat_capacity",
    "eight_lamp_system",
    "crossing_arm",
    "mirror_config",
    "lap_shoulder_belts",
)


def spec_compliance(cfg, joint_kn, derated_mi, profile):
    """Return (status, exception_count, unmet_mandatory_items)."""
    unmet = []
    if not dec(joint_kn) >= dec(profile["min_joint_strength_kn"]):
        unmet.append("joint_strength")
    if profile["requires_rollover_protection"] and not cfg["rollover_reinforcement"]:
        unmet.append("rollover_protection")
    if not dec(derated_mi) >= dec(profile["required_route_range_mi"]):
        unmet.append("route_range")
    if int(cfg["emergency_exit_count"]) < int(profile["min_emergency_exit_count"]):
        unmet.append("emergency_exits")

    exceptions = 0
    if int(cfg["seat_capacity"]) < int(profile["min_seat_capacity"]):
        exceptions += 1
    if profile["requires_eight_lamp_system"] and not cfg["eight_lamp_system"]:
        exceptions += 1
    if profile["requires_crossing_arm"] and not cfg["crossing_arm"]:
        exceptions += 1
    if MIRROR_RANK[cfg["mirror_config"]] < MIRROR_RANK[profile["required_mirror_config"]]:
        exceptions += 1
    if profile["requires_lap_shoulder_belts"] and not cfg["lap_shoulder_belts"]:
        exceptions += 1

    if unmet:
        status = "NONCONFORMING"
    elif exceptions >= 1:
        status = "EXCEPTIONS_TAKEN"
    else:
        status = "CONFORMING"
    return status, exceptions, unmet


# ------------------------------------------------------------ tests & postures

def test_minimum_value(test_type, model, profile):
    if test_type == "JOINT_STRENGTH":
        return as_number(dec(profile["min_joint_strength_kn"]))
    if test_type == "ROLLOVER":
        return as_number(round_half_up(dec(model["curb_weight_lb"]) * ROLLOVER_KN_PER_LB, 2))
    return None


def required_test_types(profile):
    required = ["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"]
    if profile["requires_joint_strength_test"]:
        required.append("JOINT_STRENGTH")
    if profile["requires_rollover_protection"]:
        required.append("ROLLOVER")
    return required


def liquidated_damages_cents(at_risk_unit_count, days_late, total_contract_cents):
    raw = cents(dec(int(at_risk_unit_count) * int(days_late) * LD_CENTS_PER_UNIT_PER_DAY))
    cap = cents(dec(total_contract_cents) * LD_CAP_PCT)
    return min(raw, cap)


def dealer_standing(open_recall_unit_count):
    if open_recall_unit_count >= DEALER_SUSPEND_THRESHOLD:
        return "SUSPENDED"
    if open_recall_unit_count >= DEALER_RESTRICT_THRESHOLD:
        return "RESTRICTED"
    return "GOOD"


STANDING_RANK = {"GOOD": 0, "RESTRICTED": 1, "SUSPENDED": 2}
