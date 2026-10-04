"""ReprintDecision routes + logical clock endpoint."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from services import compute_inventory_risk
from util import body_of, req_int, req_dt
from clock import set_clock, now_dt, iso

bp = Blueprint("reprints", __name__)
clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_endpoint():
    require_auth({"PlatformAdmin"})
    data = body_of(request)
    dt = req_dt(data, "current_utc")
    set_clock(dt)
    from campaign_routes import maybe_close_campaigns, maybe_lock_addresses
    maybe_close_campaigns()
    maybe_lock_addresses()
    return success_obj({"current_utc": iso(now_dt())})


@bp.route("/reprint-decisions", methods=["POST"])
def create_reprint():
    require_auth({"CampaignOwner"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    proposed_units = req_int(data, "proposed_units", minimum=1)
    demand_signal = req_int(data, "demand_signal_cents", minimum=0)
    score = compute_inventory_risk(campaign, demand_signal)
    decision = {
        "campaign_id": campaign_id,
        "proposed_units": proposed_units,
        "demand_signal_cents": demand_signal,
        "inventory_risk_score": score,
        "status": "PROPOSED",
    }
    stamp_new(decision)
    db.reprint_decisions[decision["id"]] = decision
    return success_obj(serialize(decision), 201)


@bp.route("/reprint-decisions/<rid>", methods=["GET"])
def get_reprint(rid):
    require_auth(ANY_ROLE)
    r = db.reprint_decisions.get(rid)
    if not r:
        raise err_not_found("reprint decision not found")
    return success_obj(serialize(r))


@bp.route("/reprint-decisions", methods=["GET"])
def list_reprints():
    require_auth(ANY_ROLE)
    items = list(db.reprint_decisions.values())
    args = request.args
    if args.get("campaign_id"):
        items = [r for r in items if r["campaign_id"] == args["campaign_id"]]
    if args.get("status"):
        items = [r for r in items if r["status"] == args["status"]]
    return paginate(items)


@bp.route("/reprint-decisions/<rid>/transition", methods=["POST"])
def reprint_transition(rid):
    user_id, role = require_auth({"CampaignOwner", "FactoryCoordinator"})
    r = db.reprint_decisions.get(rid)
    if not r:
        raise err_not_found("reprint decision not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ("approve", "reject", "lock"):
        raise err_unknown_action(f"unknown action {action}")

    if action == "approve":
        if role != "CampaignOwner":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "requires CampaignOwner")
        if r["status"] != "PROPOSED":
            raise err_invalid_state("approve requires PROPOSED")
        if int(r["inventory_risk_score"]) >= 70:
            raise ApiError("ERR_INVENTORY_RISK_TOO_HIGH", 422, "inventory risk too high")
        r["status"] = "APPROVED"
        touch(r)

    elif action == "reject":
        if role != "CampaignOwner":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "requires CampaignOwner")
        if r["status"] != "PROPOSED":
            raise err_invalid_state("reject requires PROPOSED")
        r["status"] = "REJECTED"
        touch(r)

    elif action == "lock":
        if role != "FactoryCoordinator":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "requires FactoryCoordinator")
        if r["status"] != "APPROVED":
            raise err_invalid_state("lock requires APPROVED")
        ok = any(
            q["campaign_id"] == r["campaign_id"] and q["status"] == "FINAL"
            and int(q["tier_breaks"][0]["min_units"]) <= int(r["proposed_units"])
            for q in db.quotes.values()
        )
        if not ok:
            raise ApiError("ERR_MOQ_NOT_MET", 422, "no FINAL quote with MOQ <= proposed_units")
        r["status"] = "LOCKED"
        touch(r)

    return success_obj(serialize(r))
