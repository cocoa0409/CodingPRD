"""Loading tracks and unit train shipments, with RIN separation on the BOL."""
import calc
import derive
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import (enum_param, no_body, page, pagination, require_auth,
                   str_param, take)
from store import db, new_row, touch
from util import D, dfloor, rhu

TRACK_SPEC = {
    "track_code": {"type": "string", "required": True},
    "spot_capacity": {"type": "int", "required": True, "gt": 0},
    "loading_rate_cars_per_hour": {"type": "dec", "gt": 0, "places": 1,
                                   "default": D("4.0")},
    "is_active": {"type": "bool", "default": True},
}
SHIPMENT_SPEC = {
    "shipment_code": {"type": "string", "required": True},
    "track_id": {"type": "string", "required": True},
    "expected_track_version": {"type": "int", "required": True, "ge": 1},
    "source_tank_id": {"type": "string", "required": True},
    "destination_terminal": {"type": "string", "required": True},
    "railcar_count": {"type": "int", "required": True, "gt": 0},
    "gallons_per_railcar": {"type": "dec", "required": True, "gt": 0, "places": 2},
    "window_start": {"type": "instant", "required": True},
    "window_end": {"type": "instant", "required": True},
    "price_cents_per_gallon": {"type": "dec", "required": True, "gt": 0, "places": 2},
}
BOL_SPEC = {"bol_number": {"type": "string", "required": True}}
CANCEL_SPEC = {"cancellation_reason": {"type": "string", "required": True}}

LOADING_STATUSES = ("SCHEDULED", "BLOCKED", "LOADED", "CANCELLED")
BILLING_STATUSES = ("PENDING_BOL", "BOL_ISSUED", "INVOICED", "VOIDED")


@bp.route("/loading-tracks", methods=["POST"])
def create_track():
    require_auth(["LogisticsCoordinator"])
    body = take(TRACK_SPEC)
    guards.unique(db.tracks, "track_code", body["track_code"])
    track = new_row({
        "track_code": body["track_code"],
        "spot_capacity": body["spot_capacity"],
        "loading_rate_cars_per_hour": rhu(body["loading_rate_cars_per_hour"], 1),
        "is_active": body["is_active"],
    })
    db.tracks[track["id"]] = track
    return ok(serialize.track_out(track), 201)


@bp.route("/loading-tracks/<track_id>", methods=["GET"])
def get_track(track_id):
    require_auth(["PlantManager", "LogisticsCoordinator"])
    track = guards.get_track(track_id)
    return ok(serialize.track_out(track))


@bp.route("/unit-train-shipments", methods=["POST"])
def create_shipment():
    require_auth(["LogisticsCoordinator"])
    body = take(SHIPMENT_SPEC)
    if body["window_end"] <= body["window_start"]:
        fail("ERR_VALIDATION", "window_end must be strictly after window_start")
    tank = guards.get_tank(body["source_tank_id"])
    track = guards.get_track(body["track_id"])
    guards.unique(db.shipments, "shipment_code", body["shipment_code"])
    if body["expected_track_version"] != track["version"]:
        fail("ERR_STALE_TRACK_VERSION",
             "Loading track %s is at version %d"
             % (track["track_code"], track["version"]))
    guards.require_product_type(tank, "DENATURED_E100")
    committed = derive.track_committed_railcars(
        track["id"], body["window_start"], body["window_end"])
    if committed + body["railcar_count"] > int(track["spot_capacity"]):
        fail("ERR_TRACK_CAPACITY_EXCEEDED",
             "Track %s has %d of %d railcars committed in that window"
             % (track["track_code"], committed, int(track["spot_capacity"])))
    if not track["is_active"]:
        fail("ERR_TRACK_INACTIVE",
             "Track %s is not active" % track["track_code"])
    shipment = new_row({
        "shipment_code": body["shipment_code"],
        "track_id": track["id"],
        "expected_track_version": body["expected_track_version"],
        "source_tank_id": tank["id"],
        "destination_terminal": body["destination_terminal"],
        "railcar_count": body["railcar_count"],
        "gallons_per_railcar": rhu(body["gallons_per_railcar"], 2),
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "price_cents_per_gallon": rhu(body["price_cents_per_gallon"], 2),
        "loading_status": "SCHEDULED",
        "billing_status": "PENDING_BOL",
        "planned_gallons": rhu(D(body["railcar_count"])
                               * D(body["gallons_per_railcar"]), 2),
        "loaded_gallons": None,
        "invoice_amount_cents": None,
        "bol_number": None,
        "bol_issued_at": None,
        "invoiced_at": None,
        "loaded_at": None,
        "cancelled_at": None,
        "cancellation_reason": None,
    })
    db.shipments[shipment["id"]] = shipment
    touch(track)
    return ok(serialize.shipment_out(shipment), 201)


@bp.route("/unit-train-shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    require_auth(["PlantManager", "LogisticsCoordinator", "ComplianceOfficer",
                  "RiskManager"])
    shipment = guards.get_shipment(shipment_id)
    return ok(serialize.shipment_out(shipment))


@bp.route("/unit-train-shipments", methods=["GET"])
def list_shipments():
    require_auth(["PlantManager", "LogisticsCoordinator", "ComplianceOfficer"])
    track_id = str_param("track_id")
    source_tank_id = str_param("source_tank_id")
    loading_status = enum_param("loading_status", LOADING_STATUSES)
    billing_status = enum_param("billing_status", BILLING_STATUSES)
    limit, offset = pagination()
    if source_tank_id is not None:
        guards.get_tank(source_tank_id)
    if track_id is not None:
        guards.get_track(track_id)
    rows = list(db.shipments.values())
    if track_id is not None:
        rows = [r for r in rows if r["track_id"] == track_id]
    if source_tank_id is not None:
        rows = [r for r in rows if r["source_tank_id"] == source_tank_id]
    if loading_status is not None:
        rows = [r for r in rows if r["loading_status"] == loading_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    rows = sorted(rows, key=lambda r: (r["window_start"], r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.shipment_out(r) for r in window],
                   limit, offset, len(rows))


@bp.route("/unit-train-shipments/<shipment_id>/load", methods=["POST"])
def load_shipment(shipment_id):
    require_auth(["LogisticsCoordinator"])
    no_body()
    shipment = guards.get_shipment(shipment_id)
    if shipment["loading_status"] != "SCHEDULED":
        fail("ERR_INVALID_SHIPMENT_LOADING_STATE",
             "Shipment is %s and may not be loaded" % shipment["loading_status"])
    guards.require_not_suspended()
    tank = db.tanks[shipment["source_tank_id"]]
    guards.require_tank_in_service(tank)
    if derive.tank_current_gallons(tank) < D(shipment["planned_gallons"]):
        fail("ERR_INSUFFICIENT_TANK_VOLUME",
             "Tank %s holds less than %s gallons"
             % (tank["tank_code"], format(D(shipment["planned_gallons"]), "f")))
    shipment["loading_status"] = "LOADED"
    shipment["loaded_gallons"] = rhu(shipment["planned_gallons"], 2)
    shipment["loaded_at"] = db.clock
    touch(shipment)
    touch(tank)
    return ok(serialize.shipment_out(shipment))


def _separate_rins(shipment):
    """Greedy allocation with an early stop at the first candidate that overshoots."""
    allowance = dfloor(D(shipment["loaded_gallons"]))
    candidates = [r for r in db.rins.values() if r["status"] == "GENERATED"]

    def sort_key(rin):
        batch = db.batches.get(rin["fermentation_batch_id"])
        return (rin["created_at"], batch["batch_code"] if batch else "", rin["_seq"])

    running = D(0)
    for rin in sorted(candidates, key=sort_key):
        if running + D(rin["rin_count"]) > allowance:
            break
        running += D(rin["rin_count"])
        rin["status"] = "SEPARATED"
        rin["separated_shipment_id"] = shipment["id"]
        rin["separated_at"] = db.clock
        touch(rin)


@bp.route("/unit-train-shipments/<shipment_id>/bill-of-lading", methods=["POST"])
def bill_of_lading(shipment_id):
    require_auth(["LogisticsCoordinator"])
    body = take(BOL_SPEC)
    shipment = guards.get_shipment(shipment_id)
    if shipment["loading_status"] != "LOADED":
        fail("ERR_INVALID_SHIPMENT_LOADING_STATE",
             "Shipment is %s and has nothing to document"
             % shipment["loading_status"])
    if shipment["billing_status"] != "PENDING_BOL":
        fail("ERR_INVALID_SHIPMENT_BILLING_STATE",
             "Shipment billing is %s" % shipment["billing_status"])
    shipment["billing_status"] = "BOL_ISSUED"
    shipment["bol_number"] = body["bol_number"]
    shipment["bol_issued_at"] = db.clock
    touch(shipment)
    _separate_rins(shipment)
    return ok(serialize.shipment_out(shipment))


@bp.route("/unit-train-shipments/<shipment_id>/invoice", methods=["POST"])
def invoice_shipment(shipment_id):
    require_auth(["LogisticsCoordinator"])
    no_body()
    shipment = guards.get_shipment(shipment_id)
    if shipment["billing_status"] != "BOL_ISSUED":
        fail("ERR_INVALID_SHIPMENT_BILLING_STATE",
             "Shipment billing is %s" % shipment["billing_status"])
    shipment["billing_status"] = "INVOICED"
    shipment["invoice_amount_cents"] = int(rhu(
        D(shipment["loaded_gallons"]) * D(shipment["price_cents_per_gallon"]), 0))
    shipment["invoiced_at"] = db.clock
    touch(shipment)
    return ok(serialize.shipment_out(shipment))


@bp.route("/unit-train-shipments/<shipment_id>/cancel", methods=["POST"])
def cancel_shipment(shipment_id):
    require_auth(["LogisticsCoordinator"])
    body = take(CANCEL_SPEC)
    shipment = guards.get_shipment(shipment_id)
    if shipment["loading_status"] not in ("SCHEDULED", "BLOCKED", "LOADED"):
        fail("ERR_INVALID_SHIPMENT_LOADING_STATE",
             "Shipment is %s and may not be cancelled" % shipment["loading_status"])
    if shipment["billing_status"] == "INVOICED":
        fail("ERR_SHIPMENT_ALREADY_INVOICED",
             "Shipment %s is invoiced and locked against cancellation"
             % shipment["shipment_code"])
    was_loaded = shipment["loaded_gallons"] is not None
    shipment["loading_status"] = "CANCELLED"
    shipment["billing_status"] = "VOIDED"
    shipment["cancelled_at"] = db.clock
    shipment["cancellation_reason"] = body["cancellation_reason"]
    if was_loaded:
        shipment["loaded_gallons"] = None
    touch(shipment)
    if was_loaded:
        tank = db.tanks.get(shipment["source_tank_id"])
        if tank is not None:
            touch(tank)
    track = db.tracks.get(shipment["track_id"])
    if track is not None:
        touch(track)
    for rin in db.rins.values():
        if (rin["separated_shipment_id"] == shipment["id"]
                and rin["status"] == "SEPARATED"):
            rin["status"] = "GENERATED"
            rin["separated_shipment_id"] = None
            rin["separated_at"] = None
            touch(rin)
    return ok(serialize.shipment_out(shipment))
