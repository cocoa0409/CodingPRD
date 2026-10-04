"""ReplacementRequest routes."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_forbidden, err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from services import available_spares, most_recent_locked_run
from util import body_of, req_str, req_int

bp = Blueprint("replacements", __name__)


@bp.route("/replacement-requests", methods=["POST"])
def create_replacement():
    user_id, role = require_auth({"Backer"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    pledge_id = data.get("pledge_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    if not isinstance(pledge_id, str):
        raise err_invalid_request("pledge_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    pledge = db.pledges.get(pledge_id)
    if not pledge or pledge["campaign_id"] != campaign_id:
        raise err_not_found("pledge not found")
    component_sku = req_str(data, "component_sku")
    quantity = req_int(data, "quantity", minimum=1)

    if pledge["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_PLEDGE_NOT_DELIVERED", 409, "pledge not delivered")
    if user_id != pledge["backer_user_id"]:
        raise err_forbidden()

    req = {
        "campaign_id": campaign_id,
        "pledge_id": pledge_id,
        "component_sku": component_sku,
        "quantity": quantity,
        "region_code": pledge["region_code"],
        "spare_units_debited": 0,
        "status": "PENDING",
    }
    stamp_new(req)
    db.replacement_requests[req["id"]] = req
    touch(campaign)
    return success_obj(serialize(req), 201)


@bp.route("/replacement-requests/<rid>", methods=["GET"])
def get_replacement(rid):
    require_auth(ANY_ROLE)
    r = db.replacement_requests.get(rid)
    if not r:
        raise err_not_found("replacement request not found")
    return success_obj(serialize(r))


@bp.route("/replacement-requests", methods=["GET"])
def list_replacements():
    require_auth(ANY_ROLE)
    items = list(db.replacement_requests.values())
    args = request.args
    for f in ("campaign_id", "pledge_id", "status", "region_code"):
        v = args.get(f)
        if v is not None:
            items = [r for r in items if str(r.get(f)) == v]
    return paginate(items)


@bp.route("/replacement-requests/<rid>/transition", methods=["POST"])
def replacement_transition(rid):
    user_id, role = require_auth({"CampaignOwner", "FulfillmentOperator"})
    r = db.replacement_requests.get(rid)
    if not r:
        raise err_not_found("replacement request not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ("approve", "reopen", "reject", "ship"):
        raise err_unknown_action(f"unknown action {action}")
    campaign = db.campaigns.get(r["campaign_id"])

    if action in ("approve", "reopen", "reject"):
        if role != "CampaignOwner":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "requires CampaignOwner")
    if action == "ship":
        if role != "FulfillmentOperator":
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "requires FulfillmentOperator")

    if action == "approve":
        if r["status"] != "PENDING":
            raise err_invalid_state("approve requires PENDING")
        avail = available_spares(r["campaign_id"], r["region_code"])
        if avail < int(r["quantity"]):
            raise ApiError("ERR_INSUFFICIENT_SPARES", 422, "insufficient spares")
        r["spare_units_debited"] = int(r["quantity"])
        r["status"] = "APPROVED"
        touch(r)

    elif action == "reopen":
        if r["status"] != "APPROVED":
            raise err_invalid_state("reopen requires APPROVED")
        r["spare_units_debited"] = 0
        r["status"] = "PENDING"
        touch(r)

    elif action == "reject":
        if r["status"] != "PENDING":
            raise err_invalid_state("reject requires PENDING")
        r["status"] = "REJECTED"
        touch(r)

    elif action == "ship":
        if r["status"] != "APPROVED":
            raise err_invalid_state("ship requires APPROVED")
        run = most_recent_locked_run(r["campaign_id"])
        if run:
            spares = run.setdefault("spare_units_by_region", {})
            spares[r["region_code"]] = int(spares.get(r["region_code"], 0)) - int(r["spare_units_debited"])
            touch(run)
        r["status"] = "SHIPPED"
        touch(r)
        if campaign:
            touch(campaign)

    return success_obj(serialize(r))
