# InventoryWriteDown domain (PRD 3.8): DemandPlanner proposes, FinanceController
# decides; segregation of duties between the two; reason-specific evidence
# gates; provisional full-cost valuation, NRV-based final valuation at POSTED.
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from services import batch_derived_status, nrv_for_channel
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_enum, get_int, get_str

bp = Blueprint("writedowns", __name__, url_prefix="/protein-ops/inventory-write-downs")

ANY_ROLE = constants.ROLES


@bp.route("", methods=["POST"])
def create_writedown():
    user_id, role = authenticate()
    authorize(role, ["DemandPlanner"])

    body = body_json()
    shape = Shape()
    batch_id = get_str(body, "finished_goods_batch_id", shape)
    quantity_cases = get_int(body, "quantity_cases", shape, minv=1)
    reason = get_enum(body, "reason", constants.WRITEDOWN_REASONS, shape)
    forecast_id = get_str(body, "demand_forecast_id", shape, required=False)

    # Tier 3: body FK existence in declared input order (batch, then forecast).
    batch = forecast = None
    if batch_id is not None:
        batch = db["batches"].get(batch_id)
        if batch is None:
            raise err("ERR_NOT_FOUND", "finished_goods_batch_id does not reference a batch")
    if forecast_id is not None:
        forecast = db["forecasts"].get(forecast_id)
        if forecast is None:
            raise err("ERR_NOT_FOUND", "demand_forecast_id does not reference a forecast")

    if batch is not None:
        # Tier 7 temporal: EXPIRY_RISK requires expiry at most 15 days out (or past).
        if reason == "EXPIRY_RISK":
            limit = batch["_dt"]["expiry_date"] - timedelta(days=constants.EXPIRY_RISK_WINDOW_DAYS)
            if clock.now() < limit:
                raise err("ERR_NOT_EXPIRY_RISK", "batch has more than 15 days to expiry")

        # Tier 8 structural, in sub-order: batch writability precedes the
        # quantity bound.
        derived = batch_derived_status(batch)
        if derived in ("WRITTEN_OFF", "DEPLETED"):
            raise err("ERR_BATCH_NOT_WRITABLE", "batch derived_status %s is not writable" % derived)
        if quantity_cases is not None and quantity_cases > batch["available_cases"]:
            raise err("ERR_WRITEDOWN_EXCEEDS_AVAILABLE", "quantity_cases exceeds available_cases")

        # Tier 9 cross-entity: reason-specific evidence gates, in listed order.
        if reason == "FORECAST_MISS" and forecast is not None:
            if forecast["status"] != "ACTUALIZED":
                raise err("ERR_FORECAST_NOT_ACTUALIZED", "demand forecast is not ACTUALIZED")
            if forecast["is_miss"] is not True:
                raise err("ERR_FORECAST_NO_MISS", "demand forecast is not a miss")
            if forecast["product_id"] != batch["product_id"] or forecast["channel"] != batch["channel"]:
                raise err("ERR_FORECAST_MISMATCH", "forecast product/channel does not match the batch")
        if reason == "RECALL":
            if batch["recall_flag"] is not True:
                raise err("ERR_RUN_NOT_RECALLED", "batch recall_flag is not set")

    # Tier 11: demand_forecast_id required exactly for FORECAST_MISS, null else.
    if reason == "FORECAST_MISS" and forecast_id is None:
        shape.add("demand_forecast_id", "is required when reason is FORECAST_MISS")
    if reason in ("EXPIRY_RISK", "RECALL") and forecast_id is not None:
        shape.add("demand_forecast_id", "must be null unless reason is FORECAST_MISS")
    shape.raise_if_any()

    writedown = make_entity(
        "writedowns",
        {
            "finished_goods_batch_id": batch_id,
            "demand_forecast_id": forecast_id,
            "reason": reason,
            "quantity_cases": quantity_cases,
            "proposed_by_user_id": user_id,
            "decided_by_user_id": None,
            "provisional_amount_cents": quantity_cases * batch["unit_cost_cents_per_case"],
            "final_amount_cents": None,
            "status": "PROPOSED",
        },
    )
    return success(public(writedown), "object", 201)


@bp.route("", methods=["GET"])
def list_writedowns():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["writedowns"].values())
    for param in ("finished_goods_batch_id", "demand_forecast_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [w for w in items if w.get(param) == value]
    items.sort(key=lambda w: (w["created_at"], w["_seq"]))
    page, meta = paginate([public(w) for w in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<wid>", methods=["GET"])
def get_writedown(wid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    writedown = db["writedowns"].get(wid)
    if writedown is None:
        raise err("ERR_NOT_FOUND", "inventory write-down not found")
    return success(public(writedown), "object", 200)


@bp.route("/<wid>/decision", methods=["POST"])
def decide_writedown(wid):
    user_id, role = authenticate()
    authorize(role, ["FinanceController"])

    writedown = db["writedowns"].get(wid)
    if writedown is None:
        raise err("ERR_NOT_FOUND", "inventory write-down not found")

    body = body_json()
    shape = Shape()
    decision = get_enum(body, "decision", ["POSTED", "REJECTED"], shape)

    # Tier 5: only a PROPOSED write-down can be decided.
    if writedown["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "write-down status is %s" % writedown["status"])

    # Tier 6 compliance: segregation of duties — decider may not be the proposer.
    if user_id == writedown["proposed_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "decision-maker must differ from proposed_by_user_id")

    shape.raise_if_any()

    if decision == "POSTED":
        batch = db["batches"][writedown["finished_goods_batch_id"]]
        unrecoverable = max(0, batch["unit_cost_cents_per_case"] - nrv_for_channel(batch["channel"]))
        writedown["final_amount_cents"] = writedown["quantity_cases"] * unrecoverable
        batch["available_cases"] -= writedown["quantity_cases"]
        batch["written_off_cases"] += writedown["quantity_cases"]
        mark(batch)
        writedown["status"] = "POSTED"
    else:  # REJECTED leaves the batch untouched.
        writedown["status"] = "REJECTED"
    writedown["decided_by_user_id"] = user_id
    mark(writedown)
    flush_dirty()
    return success(public(writedown), "object", 200)
