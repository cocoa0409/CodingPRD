"""Plant registration, market marks, crush margin and the logical clock."""
from decimal import Decimal

import calc
import derive
import serialize
from envelope import ok
from errors import fail
from routes import bp
from shape import ALL_ROLES, no_body, require_auth, take
from store import db, new_row, touch
from util import D, rhu

PLANT_SPEC = {
    "name": {"type": "string", "required": True, "max_len": 120},
    "nameplate_capacity_gallons": {"type": "int", "required": True, "gt": 0},
    "base_grind_cap_bushels": {"type": "int", "gt": 0, "default": 120000},
    "coverage_floor_bushels": {"type": "int", "ge": 0, "default": 200000},
    "baseline_ci_g_per_mj": {"type": "dec", "gt": 0, "places": 1,
                             "default": D("60.0")},
    "rin_generation_enabled": {"type": "bool", "default": True},
}

MARKS_SPEC = {
    "marks_effective_month": {"type": "month", "required": True},
    "mark_corn_cents_per_bushel": {"type": "dec", "required": True},
    "mark_ethanol_cents_per_gallon": {"type": "dec", "required": True},
    "mark_natgas_cents_per_mmbtu": {"type": "dec", "required": True},
    "mark_soybean_meal_usd_per_ton": {"type": "dec", "required": True},
    "mark_sbo_cents_per_lb": {"type": "dec", "required": True},
}

CLOCK_SPEC = {"current_utc": {"type": "instant", "required": True}}


@bp.route("/plants", methods=["POST"])
def create_plant():
    require_auth(["PlantManager"])
    body = take(PLANT_SPEC)
    if db.plant is not None:
        fail("ERR_PLANT_ALREADY_EXISTS", "A plant is already registered")
    plant = new_row({
        "name": body["name"],
        "nameplate_capacity_gallons": body["nameplate_capacity_gallons"],
        "base_grind_cap_bushels": body["base_grind_cap_bushels"],
        "coverage_floor_bushels": body["coverage_floor_bushels"],
        "baseline_ci_g_per_mj": rhu(body["baseline_ci_g_per_mj"], 1),
        "rin_generation_enabled": body["rin_generation_enabled"],
        "mark_corn_cents_per_bushel": None,
        "mark_ethanol_cents_per_gallon": None,
        "mark_natgas_cents_per_mmbtu": None,
        "mark_soybean_meal_usd_per_ton": None,
        "mark_sbo_cents_per_lb": None,
        "marks_effective_month": None,
        "marks_updated_at": None,
    })
    db.plant = plant
    return ok(serialize.plant_out(plant), 201)


@bp.route("/plants/<plant_id>", methods=["GET"])
def get_plant(plant_id):
    require_auth(ALL_ROLES)
    from guards import get_plant_or_404
    plant = get_plant_or_404(plant_id)
    return ok(serialize.plant_out(plant))


@bp.route("/plants/<plant_id>/market-marks", methods=["POST"])
def post_market_marks(plant_id):
    require_auth(["PlantManager", "RiskManager"])
    body = take(MARKS_SPEC)
    from guards import get_plant_or_404
    plant = get_plant_or_404(plant_id)
    for key in ("marks_effective_month", "mark_corn_cents_per_bushel",
                "mark_ethanol_cents_per_gallon", "mark_natgas_cents_per_mmbtu",
                "mark_soybean_meal_usd_per_ton", "mark_sbo_cents_per_lb"):
        plant[key] = body[key]
    plant["marks_updated_at"] = db.clock
    for position in db.positions.values():
        if position["status"] in ("OPEN", "PARTIALLY_CLOSED"):
            derive.reprice_position(position)
            touch(position)
    touch(plant)
    return ok(serialize.plant_out(plant))


@bp.route("/plants/<plant_id>/crush-margin", methods=["GET"])
def get_crush_margin(plant_id):
    require_auth(["PlantManager", "RiskManager", "GrainBuyer"])
    from guards import get_plant_or_404
    plant = get_plant_or_404(plant_id)
    for key in ("mark_corn_cents_per_bushel", "mark_ethanol_cents_per_gallon",
                "mark_natgas_cents_per_mmbtu", "mark_soybean_meal_usd_per_ton",
                "mark_sbo_cents_per_lb"):
        if plant[key] is None:
            fail("ERR_MARKS_NOT_POSTED",
                 "Market marks must be posted before reading the crush margin")

    bushels = D(0)
    for batch in db.batches.values():
        if batch["status"] == "COMPLETED":
            bushels += D(batch["corn_bushels_charged"])
    ethanol_revenue = 0
    for shipment in db.shipments.values():
        if shipment["billing_status"] == "INVOICED":
            ethanol_revenue += int(shipment["invoice_amount_cents"] or 0)
    coproduct_revenue = 0
    for sale in db.sales.values():
        if sale["status"] == "SHIPPED":
            coproduct_revenue += int(sale["invoice_amount_cents"] or 0)
    settled_cost = D(0)
    settled_bushels = D(0)
    for delivery in db.deliveries.values():
        if delivery["grading_status"] == "SETTLED":
            settled_cost += (D(delivery["net_dry_bushels"])
                             * D(delivery["net_price_cents_per_bushel"]))
            settled_bushels += D(delivery["net_dry_bushels"])

    view = calc.crush_margin(plant, derive.rolling_yield(), {
        "bushels_completed": bushels,
        "ethanol_revenue_cents": ethanol_revenue,
        "coproduct_revenue_cents": coproduct_revenue,
        "settled_cost_cents": settled_cost,
        "settled_net_dry_bushels": settled_bushels,
    })
    return ok(view)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(ALL_ROLES)
    body = take(CLOCK_SPEC)
    if body["current_utc"] <= db.clock:
        fail("ERR_CLOCK_REGRESSION",
             "current_utc must be strictly later than the current logical clock")
    db.clock = body["current_utc"]
    return ok(serialize.clock_out())
