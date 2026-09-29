"""Fermentation batches, health readings, intervention, distillation."""
from decimal import Decimal

import calc
import derive
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import (enum_param, no_body, page, pagination, require_auth, take)
from store import db, new_row, touch
from util import D, rhu

BATCH_SPEC = {
    "batch_code": {"type": "string", "required": True},
    "corn_bushels_charged": {"type": "dec", "required": True, "gt": 0, "places": 2},
    "charge_test_weight_lb_per_bu": {"type": "dec", "required": True, "gt": 0,
                                     "places": 1},
    "destination_tank_id": {"type": "string", "required": True},
}
READING_SPEC = {
    "hours_elapsed": {"type": "dec", "required": True, "ge": 0, "places": 1},
    "lactic_acid_ppm": {"type": "int", "required": True, "ge": 0},
    "acetic_acid_ppm": {"type": "int", "required": True, "ge": 0},
    "temperature_c": {"type": "dec", "required": True, "ge": 0, "le": 60, "places": 1},
}
INTERVENE_SPEC = {"intervention_note": {"type": "string", "required": True}}
DUMP_SPEC = {"dump_reason": {"type": "string", "required": True}}

BATCH_STATUSES = ("CHARGED", "FERMENTING", "HEALTH_WATCH", "DISTILLING",
                  "COMPLETED", "DUMPED")


def _reading_window(batch_id):
    rows = [r for r in db.health_readings.values() if r["batch_id"] == batch_id]
    return sorted(rows, key=lambda r: (r["hours_elapsed"], r["created_at"], r["_seq"]),
                  reverse=True)


def _recompute_index(batch):
    window = _reading_window(batch["id"])[:calc.HEALTH_WINDOW]
    batch["fermentation_health_index"] = calc.health_index(
        [r["reading_score"] for r in window])


@bp.route("/fermentation-batches", methods=["POST"])
def create_batch():
    require_auth(["ProcessOperator"])
    body = take(BATCH_SPEC)
    tank = guards.get_tank(body["destination_tank_id"])
    guards.unique(db.batches, "batch_code", body["batch_code"])
    plant = guards.get_plant_or_404()
    guards.require_not_suspended()
    guards.require_tank_in_service(tank)
    bushels = rhu(body["corn_bushels_charged"], 2)
    if bushels > D(derive.daily_grind_cap()):
        fail("ERR_GRIND_CAP_EXCEEDED",
             "The charge exceeds the plant's daily grind cap")
    guards.require_product_type(tank, "ETHANOL_200_PROOF")
    if derive.plant_corn_inventory() < bushels:
        fail("ERR_INSUFFICIENT_CORN_INVENTORY",
             "Corn inventory is below the bushels being charged")
    batch = new_row({
        "batch_code": body["batch_code"],
        "corn_bushels_charged": bushels,
        "charge_test_weight_lb_per_bu": body["charge_test_weight_lb_per_bu"],
        "destination_tank_id": tank["id"],
        "charged_at": db.clock,
        "status": "CHARGED",
        "intervention_count": 0,
        "fermentation_health_index": D("100.00"),
        "starch_bonus_gal_per_bushel": None,
        "health_penalty_gal_per_bushel": None,
        "intervention_penalty_gal_per_bushel": None,
        "effective_yield_gal_per_bushel": None,
        "ethanol_gallons_produced": None,
        "ddgs_tons_produced": None,
        "corn_oil_lbs_produced": None,
        "distillation_started_at": None,
        "completed_at": None,
        "dumped_at": None,
        "dump_reason": None,
    })
    db.batches[batch["id"]] = batch
    return ok(serialize.batch_out(batch), 201)


@bp.route("/fermentation-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    require_auth(["PlantManager", "ProcessOperator", "ComplianceOfficer",
                  "RiskManager"])
    batch = guards.get_batch(batch_id)
    return ok(serialize.batch_out(batch))


@bp.route("/fermentation-batches/<batch_id>/health-readings", methods=["POST"])
def create_health_reading(batch_id):
    require_auth(["ProcessOperator"])
    body = take(READING_SPEC)
    batch = guards.get_batch(batch_id)
    if batch["status"] not in ("CHARGED", "FERMENTING", "HEALTH_WATCH"):
        fail("ERR_INVALID_BATCH_STATE",
             "Batch is %s and accepts no further readings" % batch["status"])
    reading = new_row({
        "batch_id": batch["id"],
        "hours_elapsed": body["hours_elapsed"],
        "lactic_acid_ppm": body["lactic_acid_ppm"],
        "acetic_acid_ppm": body["acetic_acid_ppm"],
        "temperature_c": body["temperature_c"],
        "reading_score": calc.reading_score(
            body["lactic_acid_ppm"], body["acetic_acid_ppm"], body["temperature_c"]),
    }, versioned=False)
    db.health_readings[reading["id"]] = reading

    _recompute_index(batch)
    index = batch["fermentation_health_index"]
    if batch["status"] == "CHARGED":
        batch["status"] = ("FERMENTING" if index >= calc.HEALTH_WATCH_THRESHOLD
                           else "HEALTH_WATCH")
    elif batch["status"] == "FERMENTING":
        if index < calc.HEALTH_WATCH_THRESHOLD:
            batch["status"] = "HEALTH_WATCH"
    touch(batch)
    return ok(serialize.health_reading_out(reading), 201)


@bp.route("/fermentation-batches/<batch_id>/health-readings", methods=["GET"])
def list_health_readings(batch_id):
    require_auth(["PlantManager", "ProcessOperator", "ComplianceOfficer"])
    limit, offset = pagination()
    batch = guards.get_batch(batch_id)
    rows = _reading_window(batch["id"])
    window = page(rows, limit, offset)
    return ok_list([serialize.health_reading_out(r) for r in window], limit, offset,
                   len(rows))


@bp.route("/fermentation-batches/<batch_id>/intervene", methods=["POST"])
def intervene_batch(batch_id):
    require_auth(["ProcessOperator"])
    take(INTERVENE_SPEC)
    batch = guards.get_batch(batch_id)
    if batch["status"] != "HEALTH_WATCH":
        fail("ERR_INVALID_BATCH_STATE",
             "Batch is %s and may not be dosed" % batch["status"])
    if int(batch["intervention_count"]) >= calc.INTERVENTION_LIMIT:
        fail("ERR_INTERVENTION_LIMIT_REACHED",
             "This batch has already had two interventions")
    batch["intervention_count"] = int(batch["intervention_count"]) + 1
    batch["intervention_penalty_gal_per_bushel"] = calc.intervention_penalty(
        batch["intervention_count"])
    batch["status"] = "FERMENTING"
    touch(batch)
    return ok(serialize.batch_out(batch))


@bp.route("/fermentation-batches/<batch_id>/distill", methods=["POST"])
def distill_batch(batch_id):
    require_auth(["ProcessOperator"])
    no_body()
    batch = guards.get_batch(batch_id)
    if batch["status"] != "FERMENTING":
        fail("ERR_INVALID_BATCH_STATE",
             "Batch is %s and may not be distilled" % batch["status"])
    tank = db.tanks[batch["destination_tank_id"]]
    guards.require_not_suspended()
    guards.require_tank_in_service(tank)
    figures = calc.batch_yield(batch["corn_bushels_charged"],
                              batch["charge_test_weight_lb_per_bu"],
                              batch["fermentation_health_index"],
                              batch["intervention_count"])
    batch["starch_bonus_gal_per_bushel"] = figures["starch_bonus_gal_per_bushel"]
    batch["health_penalty_gal_per_bushel"] = figures["health_penalty_gal_per_bushel"]
    batch["intervention_penalty_gal_per_bushel"] = figures[
        "intervention_penalty_gal_per_bushel"]
    batch["effective_yield_gal_per_bushel"] = figures[
        "effective_yield_gal_per_bushel"]
    batch["status"] = "DISTILLING"
    batch["distillation_started_at"] = db.clock
    touch(batch)
    return ok(serialize.batch_out(batch))


@bp.route("/fermentation-batches/<batch_id>/complete", methods=["POST"])
def complete_batch(batch_id):
    require_auth(["ProcessOperator"])
    no_body()
    batch = guards.get_batch(batch_id)
    if batch["status"] != "DISTILLING":
        fail("ERR_INVALID_BATCH_STATE",
             "Batch is %s and may not be completed" % batch["status"])
    tank = db.tanks[batch["destination_tank_id"]]
    guards.require_tank_in_service(tank)
    bushels = D(batch["corn_bushels_charged"])
    ethanol = rhu(D(batch["corn_bushels_charged"])
                  * D(batch["effective_yield_gal_per_bushel"]), 2)
    if derive.tank_available_gallons(tank) < ethanol:
        fail("ERR_INSUFFICIENT_TANK_CAPACITY",
             "The destination tank cannot receive %s gallons" % ethanol)
    batch["ethanol_gallons_produced"] = ethanol
    batch["ddgs_tons_produced"] = rhu(
        bushels * calc.DDGS_LBS_PER_BUSHEL / calc.LBS_PER_TON, 3)
    batch["corn_oil_lbs_produced"] = rhu(bushels * calc.CORN_OIL_LBS_PER_BUSHEL, 2)
    batch["status"] = "COMPLETED"
    batch["completed_at"] = db.clock
    touch(batch)
    touch(tank)

    plant = db.plant
    if plant is None or plant["rin_generation_enabled"]:
        eligible, count = calc.rin_generation(ethanol)
        rin = new_row({
            "fermentation_batch_id": batch["id"],
            "rin_year": batch["completed_at"].year,
            "d_code": calc.RIN_D_CODE,
            "rin_eligible_gallons": eligible,
            "rin_count": count,
            "status": "GENERATED",
            "separated_shipment_id": None,
            "separated_at": None,
            "retired_at": None,
            "retirement_reference": None,
        })
        db.rins[rin["id"]] = rin
    return ok(serialize.batch_out(batch))


@bp.route("/fermentation-batches/<batch_id>/dump", methods=["POST"])
def dump_batch(batch_id):
    require_auth(["ProcessOperator"])
    body = take(DUMP_SPEC)
    batch = guards.get_batch(batch_id)
    if batch["status"] not in ("CHARGED", "FERMENTING", "HEALTH_WATCH"):
        fail("ERR_INVALID_BATCH_STATE",
             "Batch is %s and may not be dumped" % batch["status"])
    batch["status"] = "DUMPED"
    batch["dumped_at"] = db.clock
    batch["dump_reason"] = body["dump_reason"]
    touch(batch)
    return ok(serialize.batch_out(batch))
