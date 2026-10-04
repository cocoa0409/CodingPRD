"""Campaign routes."""
from flask import Blueprint

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_invalid_enum, err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from clock import now_dt
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from services import recompute_campaign_aggregates, evaluate_stretch_goals
from util import (body_of, req_str, req_int, req_enum, req_dt, CURRENCIES,
                  LEVEL_STATUSES, GOAL_STATUSES, ADDON_STATUSES)

bp = Blueprint("campaigns", __name__)


def _validate_levels(levels):
    if not isinstance(levels, list):
        raise err_invalid_request("pledge_levels must be an array")
    for lv in levels:
        if not isinstance(lv, dict):
            raise err_invalid_request("pledge_levels entries must be objects")
        if not isinstance(lv.get("name"), str) or not lv["name"]:
            raise err_invalid_request("pledge level name required")
        if isinstance(lv.get("price_cents"), bool) or not isinstance(lv.get("price_cents"), int):
            raise err_invalid_request("pledge level price_cents must be an integer")
        if lv.get("contents") is None:
            lv["contents"] = []
        if not isinstance(lv["contents"], list):
            raise err_invalid_request("pledge level contents must be an array")
        cap = lv.get("quantity_cap")
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int)):
            raise err_invalid_request("quantity_cap must be null or an integer")
        prem = lv.get("late_pledge_premium_pct")
        if prem is None:
            lv["late_pledge_premium_pct"] = 0
        elif isinstance(prem, bool) or not isinstance(prem, (int, float)):
            raise err_invalid_request("late_pledge_premium_pct must be a number")
        st = lv.get("status", "OPEN")
        if st not in LEVEL_STATUSES:
            raise err_invalid_enum("pledge level status invalid")
        lv["status"] = st


def _validate_goals(goals):
    if goals is None:
        return []
    if not isinstance(goals, list):
        raise err_invalid_request("stretch_goals must be an array")
    seen = set()
    for g in goals:
        if not isinstance(g, dict):
            raise err_invalid_request("stretch_goals entries must be objects")
        gid = g.get("goal_id")
        if not isinstance(gid, str) or not gid:
            raise err_invalid_request("stretch goal goal_id required")
        if gid in seen:
            raise err_invalid_request("stretch goal goal_id must be unique per campaign")
        seen.add(gid)
        if isinstance(g.get("threshold_cents"), bool) or not isinstance(g.get("threshold_cents"), int):
            raise err_invalid_request("threshold_cents must be an integer")
        if not isinstance(g.get("target_pledge_level_name"), str):
            raise err_invalid_request("target_pledge_level_name required")
        if not isinstance(g.get("bonus_component_sku"), str):
            raise err_invalid_request("bonus_component_sku required")
        st = g.get("status", "LOCKED")
        if st not in GOAL_STATUSES:
            raise err_invalid_enum("stretch goal status invalid")
        g["status"] = st
        g.setdefault("unlocked_at", None)
    return goals


def _validate_addons(addons):
    if addons is None:
        return []
    if not isinstance(addons, list):
        raise err_invalid_request("add_on_catalog must be an array")
    seen = set()
    for a in addons:
        if not isinstance(a, dict):
            raise err_invalid_request("add_on_catalog entries must be objects")
        sku = a.get("sku")
        if not isinstance(sku, str) or not sku:
            raise err_invalid_request("add-on sku required")
        if sku in seen:
            raise err_invalid_request("add-on sku must be unique per campaign")
        seen.add(sku)
        if isinstance(a.get("price_cents"), bool) or not isinstance(a.get("price_cents"), int):
            raise err_invalid_request("add-on price_cents must be an integer")
        cap = a.get("per_backer_cap")
        if isinstance(cap, bool) or not isinstance(cap, int):
            raise err_invalid_request("per_backer_cap must be an integer")
        st = a.get("status", "OPEN")
        if st not in ADDON_STATUSES:
            raise err_invalid_enum("add-on status invalid")
        a["status"] = st
    return addons


@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    user_id, role = require_auth({"CampaignOwner", "PlatformAdmin"})
    data = body_of(__import__("flask").request)
    title = req_str(data, "title")
    owner_user_id = req_str(data, "owner_user_id")
    goal_cents = req_int(data, "goal_cents", minimum=1)
    currency = req_enum(data, "currency", CURRENCIES)
    closes_at = req_dt(data, "closes_at")
    levels = data.get("pledge_levels")
    _validate_levels(levels)
    goals = _validate_goals(data.get("stretch_goals"))
    addons = _validate_addons(data.get("add_on_catalog"))

    campaign = {
        "title": title,
        "owner_user_id": owner_user_id,
        "goal_cents": goal_cents,
        "currency": currency,
        "closes_at": closes_at,
        "pledge_levels": levels,
        "stretch_goals": goals,
        "add_on_catalog": addons,
        "gross_charged_cents": 0,
        "platform_fee_cents": 0,
        "payment_fee_cents": 0,
        "customs_duty_paid_cents": 0,
        "net_payable_cents": 0,
        "total_backers_charged": 0,
        "retail_release_at": None,
        "status": "DRAFT",
    }
    stamp_new(campaign)
    db.campaigns[campaign["id"]] = campaign
    return success_obj(serialize(campaign), 201)


@bp.route("/campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    require_auth(ANY_ROLE)
    campaign = db.campaigns.get(cid)
    if not campaign:
        raise err_not_found("campaign not found")
    return success_obj(serialize(campaign))


def _close_campaign(campaign):
    """System close at closes_at; returns new status."""
    if int(campaign["gross_charged_cents"]) >= int(campaign["goal_cents"]):
        campaign["status"] = "CLOSED_SUCCESS"
        evaluate_stretch_goals(campaign)
        recompute_campaign_aggregates(campaign)
    else:
        campaign["status"] = "CLOSED_FAILED"
        for p in db.pledges.values():
            if p["campaign_id"] == campaign["id"] and p["charge_status"] in ("CHARGED", "PENDING"):
                p["charge_status"] = "REFUNDED"
                touch(p)
        campaign["gross_charged_cents"] = 0
        campaign["platform_fee_cents"] = 0
        campaign["payment_fee_cents"] = 0
        campaign["net_payable_cents"] = 0
        campaign["total_backers_charged"] = 0
        for q in db.quotes.values():
            if q["campaign_id"] == campaign["id"] and q["status"] in ("PROVISIONAL", "SUBMITTED"):
                q["status"] = "SUPERSEDED"
                touch(q)
        for r in db.production_runs.values():
            if r["campaign_id"] == campaign["id"] and r["status"] == "QUOTED":
                r["status"] = "CANCELLED"
                touch(r)
                for a in db.allocations.values():
                    if a["production_run_id"] == r["id"] and a["status"] == "RESERVED":
                        a["status"] = "RELEASED"
                        touch(a)
        for w in db.waves.values():
            if w["campaign_id"] == campaign["id"] and w["status"] in ("SCHEDULED", "OPEN"):
                w["status"] = "CANCELLED"
                for entry in w["assignments"]:
                    if entry["status"] == "ASSIGNED":
                        entry["status"] = "REMOVED"
                w["capacity_used"] = 0
                touch(w)
    touch(campaign)


@bp.route("/campaigns/<cid>/transition", methods=["POST"])
def campaign_transition(cid):
    user_id, role = require_auth({"CampaignOwner"})
    campaign = db.campaigns.get(cid)
    if not campaign:
        raise err_not_found("campaign not found")
    data = body_of(__import__("flask").request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ("launch", "unlaunch", "cancel", "start-production", "complete"):
        raise err_unknown_action(f"unknown action {action}")

    now = now_dt()

    if action == "launch":
        if campaign["status"] != "DRAFT":
            raise err_invalid_state("launch requires DRAFT")
        if not any(lv.get("status") == "OPEN" for lv in campaign["pledge_levels"]):
            raise ApiError("ERR_NO_PLEDGE_LEVEL", 409, "launch requires at least one OPEN pledge level")
        if not (campaign["closes_at"] > now):
            raise ApiError("ERR_CAMPAIGN_ALREADY_CLOSED", 409, "closes_at already passed")
        campaign["status"] = "LIVE"
        touch(campaign)

    elif action == "unlaunch":
        if campaign["status"] != "LIVE":
            raise err_invalid_state("unlaunch requires LIVE")
        if any(p["campaign_id"] == cid and p["charge_status"] == "CHARGED" for p in db.pledges.values()):
            raise ApiError("ERR_CHARGED_PLEDGES_EXIST", 409, "charged pledges exist")
        for pid, p in list(db.pledges.items()):
            if p["campaign_id"] == cid and p["charge_status"] == "PENDING":
                del db.pledges[pid]
        campaign["status"] = "DRAFT"
        touch(campaign)

    elif action == "cancel":
        if campaign["status"] not in ("DRAFT", "LIVE"):
            raise err_invalid_state("cancel requires DRAFT or LIVE")
        if any(p["campaign_id"] == cid and p["charge_status"] == "CHARGED" for p in db.pledges.values()):
            raise ApiError("ERR_CHARGED_PLEDGES_EXIST", 409, "charged pledges exist")
        if campaign["status"] == "LIVE":
            for p in db.pledges.values():
                if p["campaign_id"] == cid and p["charge_status"] == "PENDING":
                    p["charge_status"] = "REFUNDED"
                    touch(p)
        campaign["status"] = "CANCELLED"
        touch(campaign)

    elif action == "start-production":
        if campaign["status"] != "CLOSED_SUCCESS":
            raise err_invalid_state("start-production requires CLOSED_SUCCESS")
        if not any(q["campaign_id"] == cid and q["status"] == "FINAL" for q in db.quotes.values()):
            raise ApiError("ERR_NO_FINAL_QUOTE", 409, "no FINAL quote")
        if not any(r["campaign_id"] == cid and r["status"] == "LOCKED" for r in db.production_runs.values()):
            raise ApiError("ERR_NO_LOCKED_RUN", 409, "no LOCKED run")
        for r in db.production_runs.values():
            if r["campaign_id"] == cid and r["status"] == "LOCKED":
                r["status"] = "IN_PRODUCTION"
                touch(r)
        campaign["status"] = "IN_PRODUCTION"
        touch(campaign)

    elif action == "complete":
        if campaign["status"] != "FULFILLING":
            raise err_invalid_state("complete requires FULFILLING")
        if not all(w["status"] in ("DISPATCHED", "CANCELLED") for w in db.waves.values() if w["campaign_id"] == cid):
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "not all waves dispatched or cancelled")
        for p in db.pledges.values():
            if p["campaign_id"] == cid and p["charge_status"] == "CHARGED" and p["fulfillment_status"] != "DELIVERED":
                raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "charged pledge not delivered")
        for s in db.freight_shipments.values():
            run = db.production_runs.get(s["production_run_id"])
            if run and run["campaign_id"] == cid and s["status"] not in ("CLEARED", "DELIVERED"):
                raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "freight shipment not cleared")
        _finalize_retail_release(campaign)
        campaign["status"] = "COMPLETE"
        touch(campaign)

    return success_obj(serialize(campaign))


def _finalize_retail_release(campaign):
    """retail_release_window: max(latest delivered pledge ts, latest wave end) + 90d."""
    from datetime import timedelta
    delivered_ts = [
        p["updated_at"] for p in db.pledges.values()
        if p["campaign_id"] == campaign["id"] and p["fulfillment_status"] == "DELIVERED"
    ]
    wave_ends = [
        w["dispatch_window_end"] for w in db.waves.values()
        if w["campaign_id"] == campaign["id"]
    ]
    candidates = []
    if delivered_ts:
        candidates.append(max(delivered_ts))
    if wave_ends:
        candidates.append(max(wave_ends))
    if not candidates:
        campaign["retail_release_at"] = None
        return
    campaign["retail_release_at"] = max(candidates) + timedelta(days=90)


def maybe_close_campaigns():
    """Called when the logical clock advances: close LIVE campaigns at closes_at."""
    now = now_dt()
    for campaign in list(db.campaigns.values()):
        if campaign["status"] == "LIVE" and now >= campaign["closes_at"]:
            _close_campaign(campaign)


def maybe_lock_addresses():
    """CONFIRMED -> LOCKED for assigned pledges once wave.address_lock_at reached."""
    now = now_dt()
    for p in db.pledges.values():
        if p["address_status"] != "CONFIRMED":
            continue
        wid = p.get("assigned_wave_id")
        if not wid:
            continue
        wave = db.waves.get(wid)
        if wave and now >= wave["address_lock_at"]:
            p["address_status"] = "LOCKED"
            p["address_locked_at"] = now
            touch(p)
