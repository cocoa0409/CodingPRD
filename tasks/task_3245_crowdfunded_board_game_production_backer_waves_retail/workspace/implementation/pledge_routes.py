"""Pledge routes."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_forbidden, err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from clock import now_dt
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate, check_occ
from services import (compute_pledge_total, recompute_campaign_aggregates,
                      evaluate_stretch_goals)
from util import body_of, req_str, req_enum, REGIONS

bp = Blueprint("pledges", __name__)


def _resolve_level(campaign, name):
    for lv in campaign["pledge_levels"]:
        if lv["name"] == name:
            return lv
    return None


@bp.route("/pledges", methods=["POST"])
def create_pledge():
    user_id, role = require_auth({"Backer", "PlatformAdmin"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    backer_user_id = req_str(data, "backer_user_id")
    if role == "Backer" and backer_user_id != user_id:
        raise err_forbidden()
    backer_email = req_str(data, "backer_email")
    region = req_enum(data, "region_code", REGIONS)
    level_name = req_str(data, "pledge_level_name")
    is_late = data.get("is_late_pledge", False)
    if not isinstance(is_late, bool):
        raise err_invalid_request("is_late_pledge must be a boolean")
    add_on_lines = data.get("add_on_lines", [])
    if not isinstance(add_on_lines, list):
        raise err_invalid_request("add_on_lines must be an array")

    if campaign["status"] not in ("LIVE", "CLOSED_SUCCESS", "IN_PRODUCTION", "FULFILLING"):
        raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "campaign not open for pledges")
    if is_late and campaign["status"] != "CLOSED_SUCCESS":
        raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "late pledges only allowed after CLOSED_SUCCESS")

    check_occ(campaign, data)

    # unique email per campaign
    for p in db.pledges.values():
        if p["campaign_id"] == campaign_id and p["backer_email"] == backer_email:
            raise ApiError("ERR_INVALID_REQUEST", 400, "backer_email must be unique per campaign")

    level = _resolve_level(campaign, level_name)
    if level is None:
        raise err_not_found("pledge level not found")

    catalog = {a["sku"]: a for a in campaign["add_on_catalog"]}
    for line in add_on_lines:
        if not isinstance(line, dict):
            raise err_invalid_request("add_on_lines entries must be objects")
        sku = line.get("sku")
        qty = line.get("quantity")
        if not isinstance(sku, str) or sku not in catalog:
            raise err_not_found("add-on sku not found")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err_invalid_request("add-on quantity must be an integer")
        entry = catalog[sku]
        if qty < 1 or qty > int(entry["per_backer_cap"]):
            raise err_invalid_request("add-on quantity out of range")
        if entry["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "add-on not OPEN")

    total = compute_pledge_total(level, is_late, add_on_lines, catalog)
    pledge = {
        "campaign_id": campaign_id,
        "backer_user_id": backer_user_id,
        "backer_email": backer_email,
        "region_code": region,
        "pledge_level_name": level_name,
        "is_late_pledge": is_late,
        "add_on_lines": add_on_lines,
        "pledge_total_cents": total,
        "charge_status": "PENDING",
        "address_status": "UNCONFIRMED",
        "fulfillment_status": "QUEUED",
        "assigned_wave_id": None,
        "address_locked_at": None,
    }
    stamp_new(pledge)
    db.pledges[pledge["id"]] = pledge
    touch(campaign)
    return success_obj(serialize(pledge), 201)


@bp.route("/pledges/<pid>", methods=["GET"])
def get_pledge(pid):
    require_auth(ANY_ROLE)
    p = db.pledges.get(pid)
    if not p:
        raise err_not_found("pledge not found")
    return success_obj(serialize(p))


@bp.route("/pledges", methods=["GET"])
def list_pledges():
    require_auth(ANY_ROLE)
    items = list(db.pledges.values())
    args = request.args
    for f in ("campaign_id", "backer_user_id", "charge_status", "address_status",
              "fulfillment_status", "region_code"):
        v = args.get(f)
        if v is not None:
            items = [p for p in items if str(p.get(f)) == v]
    return paginate(items)


@bp.route("/pledges/<pid>/transition", methods=["POST"])
def pledge_transition(pid):
    user_id, role = require_auth({"CampaignOwner", "Backer", "PlatformAdmin"})
    p = db.pledges.get(pid)
    if not p:
        raise err_not_found("pledge not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    allowed = ("charge", "charge-retry", "refund", "confirm-address", "change-address")
    if action not in allowed:
        raise err_unknown_action(f"unknown action {action}")

    # role gating per action
    if action in ("charge", "charge-retry", "refund"):
        if role not in ("CampaignOwner", "PlatformAdmin"):
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "role not permitted for this action")
    else:  # address actions
        if role not in ("Backer", "PlatformAdmin"):
            raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "role not permitted for this action")

    campaign = db.campaigns.get(p["campaign_id"])
    now = now_dt()

    if action == "charge":
        if p["charge_status"] != "PENDING":
            raise err_invalid_state("charge requires PENDING")
        outcome = data.get("payment_outcome", "SUCCEEDED")
        if outcome == "FAILED":
            p["charge_status"] = "CHARGE_FAILED"
            touch(p)
            return success_obj(serialize(p))
        if campaign["status"] not in ("LIVE", "CLOSED_SUCCESS", "IN_PRODUCTION", "FULFILLING"):
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "campaign not chargeable")
        level = _resolve_level(campaign, p["pledge_level_name"])
        if level is None or level.get("status") != "OPEN":
            raise err_invalid_state("pledge level not OPEN")
        cap = level.get("quantity_cap")
        if cap is not None:
            charged_at_level = sum(
                1 for q in db.pledges.values()
                if q["campaign_id"] == campaign["id"]
                and q["pledge_level_name"] == level["name"]
                and q["charge_status"] == "CHARGED"
            )
            if charged_at_level >= int(cap):
                raise ApiError("ERR_LEVEL_CAPACITY_EXCEEDED", 409, "level capacity reached")
        p["charge_status"] = "CHARGED"
        touch(p)
        recompute_campaign_aggregates(campaign)
        evaluate_stretch_goals(campaign)
        recompute_campaign_aggregates(campaign)
        touch(campaign)

    elif action == "charge-retry":
        if p["charge_status"] != "CHARGE_FAILED":
            raise err_invalid_state("charge-retry requires CHARGE_FAILED")
        p["charge_status"] = "PENDING"
        touch(p)

    elif action == "refund":
        if p["charge_status"] != "CHARGED":
            raise err_invalid_state("refund requires CHARGED")
        if campaign["status"] not in ("LIVE", "CLOSED_SUCCESS", "IN_PRODUCTION", "FULFILLING"):
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "campaign not refundable")
        if p["fulfillment_status"] in ("SHIPPED", "DELIVERED"):
            raise ApiError("ERR_ALREADY_SHIPPED", 409, "pledge already shipped")
        p["charge_status"] = "REFUNDED"
        wid = p.get("assigned_wave_id")
        if wid:
            wave = db.waves.get(wid)
            if wave:
                for entry in wave["assignments"]:
                    if entry["pledge_id"] == p["id"] and entry["status"] == "ASSIGNED":
                        entry["status"] = "REMOVED"
                wave["capacity_used"] = sum(1 for e in wave["assignments"] if e["status"] == "ASSIGNED")
                touch(wave)
            p["assigned_wave_id"] = None
            p["fulfillment_status"] = "QUEUED"
        touch(p)
        recompute_campaign_aggregates(campaign)
        touch(campaign)

    elif action == "confirm-address":
        if p["address_status"] != "UNCONFIRMED":
            raise err_invalid_state("confirm-address requires UNCONFIRMED")
        if user_id != p["backer_user_id"]:
            raise err_forbidden()
        p["address_status"] = "CONFIRMED"
        touch(p)

    elif action == "change-address":
        if p["address_status"] == "LOCKED":
            raise ApiError("ERR_ADDRESS_LOCKED", 409, "address locked")
        if p["address_status"] != "CONFIRMED":
            raise err_invalid_state("change-address requires CONFIRMED")
        if user_id != p["backer_user_id"]:
            raise err_forbidden()
        wid = p.get("assigned_wave_id")
        if wid:
            wave = db.waves.get(wid)
            if wave and now >= wave["address_lock_at"]:
                raise ApiError("ERR_ADDRESS_LOCKED", 409, "address locked")
        p["address_status"] = "UNCONFIRMED"
        touch(p)

    return success_obj(serialize(p))
