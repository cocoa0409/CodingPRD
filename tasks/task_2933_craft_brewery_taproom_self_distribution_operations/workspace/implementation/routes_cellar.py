"""Cellar vessels (tanks) and the batch lifecycle."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import envelope
import helpers
import store
import validation
from errors import ApiError
from validation import ALL_ROLES, authenticate

bp = Blueprint("cellar", __name__)

TANK_TYPES = ("FERMENTER", "BRITE")
TANK_STATUSES = ("IDLE", "OCCUPIED", "DIRTY", "OUT_OF_SERVICE")
SERVICE_ACTIONS = ("CIP", "TAKE_OUT_OF_SERVICE", "RETURN_TO_SERVICE")
BATCH_STATES = ("SCHEDULED", "BREWING", "CONDITIONING", "PACKAGED", "DUMPED")
LOSS_BASES = ("PRO_RATA", "LAST_RUN_ABSORBS")
LIVE_BATCH_STATES = ("SCHEDULED", "BREWING", "CONDITIONING")


# ---------------------------------------------------------------------------
# tanks
# ---------------------------------------------------------------------------

@bp.get("/tanks")
def list_tanks():
    authenticate(ALL_ROLES)
    status = validation.query_enum("status", TANK_STATUSES)
    tank_type = validation.query_enum("tank_type", TANK_TYPES)

    def predicate(row):
        return (helpers.matches(row, "status", status)
                and helpers.matches(row, "tank_type", tank_type))

    rows, limit, offset, total = helpers.listing("tanks", derive.serialize_tank, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/tanks/<tank_id>")
def read_tank(tank_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_tank(helpers.find("tanks", tank_id)))


@bp.post("/tanks")
def create_tank():
    authenticate(["BreweryAdmin", "CellarOperator"])
    payload = validation.body()
    code = validation.field_string(payload, "code", 1, 16)
    tank_type = validation.field_enum(payload, "tank_type", TANK_TYPES)
    capacity = validation.field_number(payload, "capacity_bbl", 2, exclusive_minimum=0)
    helpers.unique("tanks", code)
    row = store.new_row({
        "code": code,
        "tank_type": tank_type,
        "capacity_bbl": calc.bbl2(capacity),
        "status": "IDLE",
        "last_cip_utc": None,
        "cip_cycle_count": 0,
        "occupying_batch_id": None,
    })
    helpers.insert("tanks", row)
    return envelope.object_response(derive.serialize_tank(row), 201)


@bp.post("/tanks/<tank_id>/service")
def service_tank(tank_id):
    authenticate(["CellarOperator"])
    payload = validation.body()
    action = validation.field_enum(payload, "action", SERVICE_ACTIONS)
    tank = helpers.find("tanks", tank_id)

    legal = {
        "CIP": ("DIRTY",),
        "TAKE_OUT_OF_SERVICE": ("IDLE",),
        "RETURN_TO_SERVICE": ("OUT_OF_SERVICE",),
    }
    if tank.get("status") not in legal[action]:
        raise ApiError("ERR_TANK_TRANSITION_INVALID")

    if action == "CIP":
        ppm = validation.field_int(payload, "sanitizer_ppm")
        seconds = validation.field_int(payload, "contact_time_seconds")
        if not calc.sanitation_passes(ppm, seconds):
            raise ApiError("ERR_SANITATION_BELOW_STANDARD")
        tank["status"] = "IDLE"
        tank["last_cip_utc"] = helpers.now()
        tank["cip_cycle_count"] = (tank.get("cip_cycle_count") or 0) + 1
    elif action == "TAKE_OUT_OF_SERVICE":
        tank["status"] = "OUT_OF_SERVICE"
    else:
        tank["status"] = "IDLE"
    store.touch(tank)
    return envelope.object_response(derive.serialize_tank(tank))


# ---------------------------------------------------------------------------
# batches
# ---------------------------------------------------------------------------

@bp.get("/batches")
def list_batches():
    authenticate(ALL_ROLES)
    beer_id = validation.query_string("beer_id")
    tank_id = validation.query_string("tank_id")
    state = validation.query_enum("state", BATCH_STATES)

    def predicate(row):
        return (helpers.matches(row, "beer_id", beer_id)
                and helpers.matches(row, "tank_id", tank_id)
                and helpers.matches(row, "state", state))

    rows, limit, offset, total = helpers.listing("batches", derive.serialize_batch, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/batches/<batch_id>")
def read_batch(batch_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_batch(helpers.find("batches", batch_id)))


@bp.post("/batches")
def create_batch():
    authenticate(["CellarOperator"])
    payload = validation.body()
    beer_id = validation.field_id(payload, "beer_id")
    tank_id = validation.field_id(payload, "tank_id")
    batch_code = validation.field_string(payload, "batch_code", 1, 24)
    planned = validation.field_number(payload, "planned_volume_bbl", 2, exclusive_minimum=0)
    brew_start = validation.field_datetime(payload, "brew_start_utc")
    brew_end = validation.field_datetime(payload, "brew_end_utc")
    validation.require_interval("brew_start_utc", brew_start, "brew_end_utc", brew_end)
    loss_basis = validation.field_enum(payload, "loss_basis", LOSS_BASES,
                                       required=False, default="PRO_RATA")

    helpers.find("beers", beer_id)
    tank = helpers.find("tanks", tank_id)
    helpers.unique("batches", batch_code)

    buffer_delta = timedelta(hours=calc.TANK_CIP_BUFFER_HOURS)
    window_start = brew_start - buffer_delta
    window_end = brew_end + buffer_delta
    for other in derive.rows("batches"):
        if other.get("tank_id") != tank_id:
            continue
        if other.get("state") not in LIVE_BATCH_STATES:
            continue
        if other["brew_start_utc"] < window_end and window_start < other["brew_end_utc"]:
            raise ApiError("ERR_TANK_SCHEDULE_CONFLICT")

    if Decimal(planned) > Decimal(tank["capacity_bbl"]):
        raise ApiError("ERR_TANK_CAPACITY_EXCEEDED")

    row = store.new_row({
        "beer_id": beer_id,
        "tank_id": tank_id,
        "batch_code": batch_code,
        "planned_volume_bbl": calc.bbl2(planned),
        "brew_start_utc": brew_start,
        "brew_end_utc": brew_end,
        "loss_basis": loss_basis,
        "state": "SCHEDULED",
        "actual_yield_bbl": None,
        "total_loss_bbl": None,
        "dumped_reason": None,
    })
    helpers.insert("batches", row)
    return envelope.object_response(derive.serialize_batch(row), 201)


@bp.post("/batches/<batch_id>/start")
def start_batch(batch_id):
    authenticate(["CellarOperator"])
    validation.body()
    batch = helpers.find("batches", batch_id)
    if batch.get("state") != "SCHEDULED":
        raise ApiError("ERR_BATCH_TRANSITION_INVALID")
    helpers.require_notice_active()
    tank = helpers.find("tanks", batch["tank_id"])
    if tank.get("status") != "IDLE":
        raise ApiError("ERR_TANK_NOT_IDLE")
    batch["state"] = "BREWING"
    tank["status"] = "OCCUPIED"
    tank["occupying_batch_id"] = batch["id"]
    store.touch(batch)
    store.touch(tank)
    return envelope.object_response(derive.serialize_batch(batch))


@bp.post("/batches/<batch_id>/condition")
def condition_batch(batch_id):
    authenticate(["CellarOperator"])
    payload = validation.body()
    actual_yield = validation.field_number(payload, "actual_yield_bbl", 3, exclusive_minimum=0)
    batch = helpers.find("batches", batch_id)
    if batch.get("state") != "BREWING":
        raise ApiError("ERR_BATCH_TRANSITION_INVALID")
    tank = helpers.find("tanks", batch["tank_id"])
    if Decimal(actual_yield) > Decimal(tank["capacity_bbl"]):
        raise ApiError("ERR_TANK_CAPACITY_EXCEEDED")
    batch["state"] = "CONDITIONING"
    batch["actual_yield_bbl"] = calc.bbl(actual_yield)
    store.touch(batch)
    return envelope.object_response(derive.serialize_batch(batch))


@bp.post("/batches/<batch_id>/dump")
def dump_batch(batch_id):
    authenticate(["CellarOperator"])
    payload = validation.body()
    reason = validation.field_string(payload, "reason", 1, None)
    batch = helpers.find("batches", batch_id)
    state = batch.get("state")
    if state not in LIVE_BATCH_STATES:
        raise ApiError("ERR_BATCH_TRANSITION_INVALID")

    if state == "CONDITIONING":
        for run in derive.runs_of_batch(batch["id"]):
            if run.get("state") == "PLANNED":
                raise ApiError("ERR_BATCH_HAS_PLANNED_RUNS")

    seen = set()
    batch["state"] = "DUMPED"
    batch["dumped_reason"] = reason
    if state == "CONDITIONING" and batch.get("actual_yield_bbl") is not None:
        batch["total_loss_bbl"] = calc.bbl(
            Decimal(batch["actual_yield_bbl"]) - derive.packaged_bbl(batch))
    if state in ("BREWING", "CONDITIONING"):
        tank = helpers.find("tanks", batch["tank_id"])
        if tank.get("status") == "OCCUPIED":
            tank["status"] = "DIRTY"
            tank["occupying_batch_id"] = None
            cascades.touch_once(tank, seen)
    cascades.touch_once(batch, seen)
    return envelope.object_response(derive.serialize_batch(batch))
