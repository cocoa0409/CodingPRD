"""Distribution endpoints (PRD 3.6): shipments, actions, readings, excursions."""
from decimal import Decimal

from flask import Blueprint, request

import calc_quality
import clock
import envelope
import serialize
import store
from auth import require_auth
from constants import (
    DEMAND_TYPES,
    DETECT_FREEZE_BELOW_MIN_C,
    DETECT_MAX_EXCURSION_COUNT,
    DETECT_SPIKE_ABOVE_MAX_C,
    SHIPMENT_ACTIONS,
)
from errors import err
from validate import action_value, body, must_get, paginate, req_dt, req_enum, req_num, req_str

bp = Blueprint("shipments", __name__)


def _site_of_batch(batch):
    campaign = store.get("campaigns", batch["campaign_id"])
    train = store.get("trains", campaign["train_id"])
    return store.get("sites", train["site_id"])


@bp.route("/batches/<bid>/shipments", methods=["POST"])
def create_shipment(bid):
    require_auth(("SupplyPlanner",))
    batch = must_get("batch", bid)
    d = body()
    region = req_str(d, "destination_region")
    market = req_enum(d, "market_type", DEMAND_TYPES)
    qty = req_num(d, "quantity_units")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
        err("ERR_INVALID_REQUEST", "quantity_units must be an integer >= 1")
    # PRD 3.6 order: release gate, market match, availability, cold storage.
    if batch["quality_status"] != "RELEASED":
        err("ERR_BATCH_NOT_RELEASED", "Shipment creation requires batch RELEASED")
    campaign = store.get("campaigns", batch["campaign_id"])
    if market != campaign["demand_type"]:
        err("ERR_MARKET_SCOPE_VIOLATION",
            "shipment market_type differs from the campaign demand_type")
    if qty > serialize.available_to_ship(batch):
        err("ERR_SHIPMENT_QUANTITY_EXCEEDS_AVAILABLE",
            "quantity_units exceeds batch available_to_ship_units")
    site = _site_of_batch(batch)
    occupied = sum(
        s["quantity_units"] for s in store.all_recs("shipments")
        if s["status"] == "PLANNED"
        and _site_of_batch(store.get("batches", s["batch_lot_id"]))["id"] == site["id"])
    if occupied + qty > site["cold_storage_capacity_units"]:
        err("ERR_COLD_STORAGE_CAPACITY_EXCEEDED",
            "Aggregate PLANNED shipment quantity would exceed cold storage capacity")
    rec = store.create_rec("shipments", {
        "batch_lot_id": batch["id"],
        "destination_region": region,
        "market_type": market,
        "quantity_units": qty,
        "status": "PLANNED",
        "shipped_at": None,
        "delivered_at": None,
        "excursion_evaluation": "NONE",
        "evaluation_variant": "NONE",
    })
    return envelope.ok(serialize.shipment(rec), 201)


@bp.route("/batches/<bid>/shipments", methods=["GET"])
def list_shipments(bid):
    require_auth(("Any",))
    must_get("batch", bid)
    recs = [s for s in store.all_recs("shipments") if s["batch_lot_id"] == bid]
    status_f = request.args.get("status")
    if status_f is not None:
        recs = [s for s in recs if s["status"] == status_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.shipment(s) for s in page], total, limit, offset)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    require_auth(("Any",))
    return envelope.ok(serialize.shipment(must_get("shipment", sid)), 200)


@bp.route("/shipments/<sid>/action", methods=["POST"])
def shipment_action(sid):
    require_auth(("SupplyPlanner",))
    rec = must_get("shipment", sid)
    d = body()
    act = action_value(d, "action", SHIPMENT_ACTIONS)
    if act == "SHIP":
        if rec["status"] != "PLANNED":
            err("ERR_INVALID_SHIPMENT_STATE", "SHIP requires PLANNED")
        rec["status"] = "IN_TRANSIT"  # cold-storage occupancy released
        rec["shipped_at"] = clock.now()
    elif act == "CANCEL":
        if rec["status"] != "PLANNED":
            err("ERR_INVALID_SHIPMENT_STATE", "CANCEL requires PLANNED")
        rec["status"] = "CANCELLED"  # occupancy released; availability restored
    else:  # DELIVER
        if rec["status"] != "IN_TRANSIT":
            err("ERR_INVALID_SHIPMENT_STATE", "DELIVER requires IN_TRANSIT")
        batch = store.get("batches", rec["batch_lot_id"])
        if clock.now() > batch["expiry_utc"]:  # exactly at expiry is allowed
            err("ERR_BATCH_EXPIRED", "Logical clock is past batch expiry_utc")
        rec["status"] = "DELIVERED"
        rec["delivered_at"] = clock.now()
    store.touch(rec)
    return envelope.ok(serialize.shipment(rec), 200)


@bp.route("/shipments/<sid>/readings", methods=["POST"])
def record_reading(sid):
    require_auth(("SupplyPlanner",))
    shipment = must_get("shipment", sid)
    d = body()
    recorded = req_dt(d, "recorded_at")
    temp = req_num(d, "temperature_c")
    rec = store.create_rec("readings", {
        "shipment_id": shipment["id"],
        "recorded_at": recorded,
        "temperature_c": temp,
    }, common=False)
    if shipment["status"] == "IN_TRANSIT":
        batch = store.get("batches", shipment["batch_lot_id"])
        product = store.get("products", batch["product_id"])
        hi = Decimal(str(product["max_storage_temp_c"]))
        lo = Decimal(str(product["min_storage_temp_c"]))
        t = Decimal(str(temp))
        over_count = sum(
            1 for r in store.all_recs("readings")
            if r["shipment_id"] == shipment["id"]
            and Decimal(str(r["temperature_c"])) > hi)
        if t > hi + DETECT_SPIKE_ABOVE_MAX_C \
                or t < lo - DETECT_FREEZE_BELOW_MIN_C \
                or over_count > DETECT_MAX_EXCURSION_COUNT:
            shipment["status"] = "EXCURSION_HOLD"
            shipment["excursion_evaluation"] = "PENDING"
            store.touch(shipment)
    return envelope.ok(serialize.reading(rec), 201)


@bp.route("/shipments/<sid>/readings", methods=["GET"])
def list_readings(sid):
    require_auth(("Any",))
    must_get("shipment", sid)
    recs = [r for r in store.all_recs("readings") if r["shipment_id"] == sid]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.reading(r) for r in page], total, limit, offset)


@bp.route("/shipments/<sid>/evaluate-excursion", methods=["POST"])
def evaluate_excursion(sid):
    require_auth(("QualityAssuranceReviewer",))
    rec = must_get("shipment", sid)
    if rec["status"] != "EXCURSION_HOLD":
        err("ERR_INVALID_SHIPMENT_STATE", "evaluate-excursion requires EXCURSION_HOLD")
    batch = store.get("batches", rec["batch_lot_id"])
    product = store.get("products", batch["product_id"])
    readings = [r for r in store.all_recs("readings") if r["shipment_id"] == rec["id"]]
    verdict, variant = calc_quality.excursion_verdict(rec, product, readings)
    rec["excursion_evaluation"] = verdict
    rec["evaluation_variant"] = variant
    rec["status"] = "IN_TRANSIT" if verdict == "ACCEPTABLE" else "QUARANTINED"
    store.touch(rec)
    return envelope.ok(serialize.shipment(rec), 200)
