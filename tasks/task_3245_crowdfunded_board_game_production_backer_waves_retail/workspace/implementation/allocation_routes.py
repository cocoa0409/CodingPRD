"""DistributorAllocation routes."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_forbidden, err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from clock import now_dt
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from util import body_of, req_str, req_int, req_enum, req_num, REGIONS

bp = Blueprint("allocations", __name__)


@bp.route("/distributor-allocations", methods=["POST"])
def create_allocation():
    require_auth({"PlatformAdmin"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    run_id = data.get("production_run_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    if not isinstance(run_id, str):
        raise err_invalid_request("production_run_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    run = db.production_runs.get(run_id)
    if not run or run["campaign_id"] != campaign_id:
        raise err_not_found("production run not found")
    distributor_user_id = req_str(data, "distributor_user_id")
    distributor_name = req_str(data, "distributor_name")
    region = req_enum(data, "region_code", REGIONS)
    msrp = req_num(data, "msrp_positioning_pct")
    if not (0.30 <= float(msrp) <= 0.60):
        raise err_invalid_request("msrp_positioning_pct must be in [0.30, 0.60]")
    priority = req_int(data, "allocation_priority")
    units_reserved = req_int(data, "units_reserved", minimum=1)

    # allocatable pool (PRD §3.8): planned_units of the run drawing the units
    # (this allocation's own production_run_id), minus CHARGED pledges on the
    # campaign, minus spare_units_by_region across the four regions (drawn
    # from the campaign's most recently LOCKED run, the canonical spare pool
    # per PRD §3.9), minus active reservations on the run.
    charged = sum(1 for p in db.pledges.values()
                  if p["campaign_id"] == campaign_id and p["charge_status"] == "CHARGED")
    locked_runs = [r for r in db.production_runs.values()
                   if r["campaign_id"] == campaign_id
                   and r.get("spare_units_by_region") is not None]
    if locked_runs:
        locked_runs.sort(key=lambda r: r.get("_seq", 0))
        spare_run = locked_runs[-1]
        spares = sum(int(v) for v in (spare_run.get("spare_units_by_region") or {}).values())
    else:
        spares = 0
    reserved = sum(int(a["units_reserved"]) for a in db.allocations.values()
                   if a["production_run_id"] == run_id
                   and a["status"] in ("RESERVED", "CONFIRMED", "SHIPPED"))
    pool = int(run.get("planned_units") or 0) - charged - spares - reserved
    if pool == 0 or units_reserved > pool:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_POOL", 422,
                       "units_reserved exceeds allocatable pool")

    alloc = {
        "campaign_id": campaign_id,
        "distributor_user_id": distributor_user_id,
        "distributor_name": distributor_name,
        "region_code": region,
        "msrp_positioning_pct": msrp,
        "allocation_priority": priority,
        "production_run_id": run_id,
        "units_reserved": units_reserved,
        "status": "RESERVED",
    }
    stamp_new(alloc)
    db.allocations[alloc["id"]] = alloc
    touch(campaign)
    return success_obj(serialize(alloc), 201)


@bp.route("/distributor-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    require_auth(ANY_ROLE)
    a = db.allocations.get(aid)
    if not a:
        raise err_not_found("allocation not found")
    return success_obj(serialize(a))


@bp.route("/distributor-allocations", methods=["GET"])
def list_allocations():
    require_auth(ANY_ROLE)
    items = list(db.allocations.values())
    args = request.args
    for f in ("campaign_id", "distributor_user_id", "production_run_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [a for a in items if str(a.get(f)) == v]
    return paginate(items)


@bp.route("/distributor-allocations/<aid>/transition", methods=["POST"])
def allocation_transition(aid):
    user_id, role = require_auth({"Distributor", "FulfillmentOperator"})
    a = db.allocations.get(aid)
    if not a:
        raise err_not_found("allocation not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ("confirm", "ship", "release"):
        raise err_unknown_action(f"unknown action {action}")
    campaign = db.campaigns.get(a["campaign_id"])
    now = now_dt()

    if action == "confirm":
        if role != "Distributor":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "confirm requires Distributor")
        if a["status"] != "RESERVED":
            raise err_invalid_state("confirm requires RESERVED")
        if campaign["status"] not in ("FULFILLING", "COMPLETE"):
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "campaign not FULFILLING/COMPLETE")
        if user_id != a["distributor_user_id"]:
            raise err_forbidden()
        a["status"] = "CONFIRMED"
        touch(a)

    elif action == "ship":
        if role != "FulfillmentOperator":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "ship requires FulfillmentOperator")
        if a["status"] != "CONFIRMED":
            raise err_invalid_state("ship requires CONFIRMED")
        if campaign["retail_release_at"] is None or now < campaign["retail_release_at"]:
            raise ApiError("ERR_RETAIL_RELEASE_TOO_EARLY", 409, "before retail release")
        a["status"] = "SHIPPED"
        touch(a)

    elif action == "release":
        if role != "Distributor":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "release requires Distributor")
        if a["status"] != "RESERVED":
            raise err_invalid_state("release requires RESERVED")
        if user_id != a["distributor_user_id"]:
            raise err_forbidden()
        a["status"] = "RELEASED"
        touch(a)

    return success_obj(serialize(a))
