"""FreightShipment routes."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from clock import now_dt
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from services import (compute_customs_duty, freight_preview_cost,
                      recompute_campaign_aggregates)
from run_routes import maybe_ship_run
from util import body_of, req_enum, req_int, req_dt, req_num, REGIONS

bp = Blueprint("freight", __name__)

ACTIVE_STATUSES = {"IN_TRANSIT", "CUSTOMS_HOLD", "DUTY_ASSESSED", "CLEARED"}


def _windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _check_overlap(run_id, departs, arrives, exclude_id=None):
    for s in db.freight_shipments.values():
        if s["production_run_id"] != run_id:
            continue
        if exclude_id and s["id"] == exclude_id:
            continue
        if s["status"] not in ACTIVE_STATUSES:
            continue
        if _windows_overlap(departs, arrives, s["departs_at"], s["arrives_at"]):
            raise ApiError("ERR_FREIGHT_WINDOW_OVERLAP", 409,
                           "freight window overlaps another active shipment on the run")


@bp.route("/freight-shipments", methods=["POST"])
def create_shipment():
    require_auth({"FreightBroker"})
    data = body_of(request)
    run_id = data.get("production_run_id")
    if not isinstance(run_id, str):
        raise err_invalid_request("production_run_id is required")
    run = db.production_runs.get(run_id)
    if not run:
        raise err_not_found("production run not found")
    region = req_enum(data, "region_code", REGIONS)
    container_count = req_int(data, "container_count", minimum=1)
    declared_value = req_int(data, "declared_value_cents", minimum=1)
    departs = req_dt(data, "departs_at")
    arrives = req_dt(data, "arrives_at")
    if not (arrives > departs):
        raise err_invalid_request("arrives_at must be after departs_at")
    dry_run = data.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise err_invalid_request("dry_run must be a boolean")

    if dry_run:
        weight = req_num(data, "total_weight_kg")
        volume = req_num(data, "total_volume_m3")
        cost = freight_preview_cost(region, container_count, weight, volume)
        preview = {
            "production_run_id": run_id,
            "region_code": region,
            "container_count": container_count,
            "declared_value_cents": declared_value,
            "departs_at": departs,
            "arrives_at": arrives,
            "customs_duty_cents": None,
            "cost_cents": cost,
            "duty_variant_used": None,
            "status": "BOOKED",
        }
        return success_obj(serialize(preview), 201)

    _check_overlap(run_id, departs, arrives)

    shipment = {
        "production_run_id": run_id,
        "region_code": region,
        "container_count": container_count,
        "declared_value_cents": declared_value,
        "departs_at": departs,
        "arrives_at": arrives,
        "customs_duty_cents": None,
        "cost_cents": None,
        "duty_variant_used": None,
        "status": "BOOKED",
    }
    stamp_new(shipment)
    db.freight_shipments[shipment["id"]] = shipment
    return success_obj(serialize(shipment), 201)


@bp.route("/freight-shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    require_auth(ANY_ROLE)
    s = db.freight_shipments.get(sid)
    if not s:
        raise err_not_found("shipment not found")
    return success_obj(serialize(s))


@bp.route("/freight-shipments", methods=["GET"])
def list_shipments():
    require_auth(ANY_ROLE)
    items = list(db.freight_shipments.values())
    args = request.args
    if args.get("production_run_id"):
        items = [s for s in items if s["production_run_id"] == args["production_run_id"]]
    if args.get("region_code"):
        items = [s for s in items if s["region_code"] == args["region_code"]]
    if args.get("status"):
        items = [s for s in items if s["status"] == args["status"]]
    return paginate(items)


ACTION_ROLES = {
    "depart": {"FreightBroker"},
    "arrive": {"FreightBroker"},
    "assess-duty": {"CustomsAgent"},
    "pay-duty": {"CustomsAgent"},
    "rebook": {"FreightBroker"},
    "deliver-to-warehouse": {"FulfillmentOperator"},
}


@bp.route("/freight-shipments/<sid>/transition", methods=["POST"])
def shipment_transition(sid):
    user_id, role = require_auth({"FreightBroker", "CustomsAgent", "FulfillmentOperator"})
    s = db.freight_shipments.get(sid)
    if not s:
        raise err_not_found("shipment not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ACTION_ROLES:
        raise err_unknown_action(f"unknown action {action}")
    if role not in ACTION_ROLES[action]:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "role not permitted for this action")

    run = db.production_runs.get(s["production_run_id"])
    campaign = db.campaigns.get(run["campaign_id"]) if run else None
    now = now_dt()

    if action == "depart":
        if s["status"] != "BOOKED":
            raise err_invalid_state("depart requires BOOKED")
        if now < s["departs_at"]:
            raise ApiError("ERR_FREIGHT_NOT_IN_WINDOW", 409, "before departs_at")
        _check_overlap(s["production_run_id"], s["departs_at"], s["arrives_at"], exclude_id=sid)
        s["status"] = "IN_TRANSIT"
        touch(s)

    elif action == "arrive":
        if s["status"] != "IN_TRANSIT":
            raise err_invalid_state("arrive requires IN_TRANSIT")
        if now < s["arrives_at"]:
            raise ApiError("ERR_FREIGHT_NOT_IN_WINDOW", 409, "before arrives_at")
        s["status"] = "CUSTOMS_HOLD"
        touch(s)

    elif action == "assess-duty":
        if s["status"] != "CUSTOMS_HOLD":
            raise err_invalid_state("assess-duty requires CUSTOMS_HOLD")
        duty, variant = compute_customs_duty(s)
        s["customs_duty_cents"] = duty
        s["duty_variant_used"] = variant
        s["status"] = "DUTY_ASSESSED"
        touch(s)

    elif action == "pay-duty":
        if s["status"] != "DUTY_ASSESSED":
            raise err_invalid_state("pay-duty requires DUTY_ASSESSED")
        s["status"] = "CLEARED"
        touch(s)
        if campaign:
            recompute_campaign_aggregates(campaign)
            touch(campaign)

    elif action == "rebook":
        if s["status"] != "CUSTOMS_HOLD":
            raise err_invalid_state("rebook requires CUSTOMS_HOLD")
        departs = req_dt(data, "departs_at")
        arrives = req_dt(data, "arrives_at")
        if not (arrives > departs):
            raise err_invalid_request("arrives_at must be after departs_at")
        _check_overlap(s["production_run_id"], departs, arrives, exclude_id=sid)
        s["departs_at"] = departs
        s["arrives_at"] = arrives
        s["status"] = "BOOKED"
        touch(s)

    elif action == "deliver-to-warehouse":
        if s["status"] != "CLEARED":
            raise err_invalid_state("deliver-to-warehouse requires CLEARED")
        s["status"] = "DELIVERED"
        touch(s)
        maybe_ship_run(s["production_run_id"])

    return success_obj(serialize(s))
