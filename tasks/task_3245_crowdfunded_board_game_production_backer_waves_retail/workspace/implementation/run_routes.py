"""ProductionRun routes."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from clock import now_dt
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from services import compute_spares
from util import body_of

bp = Blueprint("production_runs", __name__)


@bp.route("/production-runs", methods=["POST"])
def create_run():
    require_auth({"FactoryCoordinator"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    quote_id = data.get("quote_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    if not isinstance(quote_id, str):
        raise err_invalid_request("quote_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    quote = db.quotes.get(quote_id)
    if not quote or quote["campaign_id"] != campaign_id:
        raise err_not_found("quote not found")

    run = {
        "campaign_id": campaign_id,
        "quote_id": quote_id,
        "planned_units": None,
        "spare_units_by_region": {},
        "_initial_spare_units_by_region": {},
        "_locked_at": None,
        "status": "QUOTED",
    }
    stamp_new(run)
    db.production_runs[run["id"]] = run
    touch(campaign)
    return success_obj(serialize(run), 201)


@bp.route("/production-runs/<rid>", methods=["GET"])
def get_run(rid):
    require_auth(ANY_ROLE)
    r = db.production_runs.get(rid)
    if not r:
        raise err_not_found("production run not found")
    out = serialize(r)
    out.pop("_initial_spare_units_by_region", None)
    out.pop("_locked_at", None)
    return success_obj(out)


@bp.route("/production-runs", methods=["GET"])
def list_runs():
    require_auth(ANY_ROLE)
    items = list(db.production_runs.values())
    args = request.args
    if args.get("campaign_id"):
        items = [r for r in items if r["campaign_id"] == args["campaign_id"]]
    if args.get("quote_id"):
        items = [r for r in items if r["quote_id"] == args["quote_id"]]
    if args.get("status"):
        items = [r for r in items if r["status"] == args["status"]]
    resp = paginate(items)
    return resp


@bp.route("/production-runs/<rid>/transition", methods=["POST"])
def run_transition(rid):
    require_auth({"FactoryCoordinator"})
    r = db.production_runs.get(rid)
    if not r:
        raise err_not_found("production run not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ("lock", "cancel"):
        raise err_unknown_action(f"unknown action {action}")
    campaign = db.campaigns.get(r["campaign_id"])
    quote = db.quotes.get(r["quote_id"])

    if action == "lock":
        if r["status"] != "QUOTED":
            raise err_invalid_state("lock requires QUOTED")
        if not quote or quote["status"] != "FINAL":
            raise ApiError("ERR_QUOTE_NOT_FINAL", 409, "quote not FINAL")
        moq = int(quote["tier_breaks"][0]["min_units"])
        if int(quote["final_units"] or 0) < moq:
            raise ApiError("ERR_MOQ_NOT_MET", 422, "final_units below MOQ")
        r["planned_units"] = int(quote["final_units"])
        spares = compute_spares(r["planned_units"])
        r["spare_units_by_region"] = dict(spares)
        r["_initial_spare_units_by_region"] = dict(spares)
        r["_locked_at"] = now_dt()
        r["status"] = "LOCKED"
        touch(r)
        if campaign:
            touch(campaign)

    elif action == "cancel":
        if r["status"] != "QUOTED":
            raise err_invalid_state("cancel requires QUOTED")
        r["status"] = "CANCELLED"
        touch(r)
        for a in db.allocations.values():
            if a["production_run_id"] == rid and a["status"] == "RESERVED":
                a["status"] = "RELEASED"
                touch(a)

    return success_obj(serialize(r))


def maybe_ship_run(run_id):
    """System: all freight shipments DELIVERED -> run IN_PRODUCTION -> SHIPPED."""
    r = db.production_runs.get(run_id)
    if not r or r["status"] != "IN_PRODUCTION":
        return
    shipments = [s for s in db.freight_shipments.values() if s["production_run_id"] == run_id]
    if shipments and all(s["status"] == "DELIVERED" for s in shipments):
        r["status"] = "SHIPPED"
        touch(r)
