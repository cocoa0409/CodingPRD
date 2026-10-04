"""Wave routes: lifecycle + assignment operations."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from clock import now_dt
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate, check_occ
from util import body_of, req_enum, req_int, req_dt, opt_dt, opt_int, REGIONS

bp = Blueprint("waves", __name__)


def _wave_capacity_used(wave):
    return sum(1 for e in wave["assignments"] if e["status"] == "ASSIGNED")


def _sync_capacity(wave):
    wave["capacity_used"] = _wave_capacity_used(wave)


@bp.route("/waves", methods=["POST"])
def create_wave():
    require_auth({"FulfillmentOperator"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    region = req_enum(data, "region_code", REGIONS)
    sequence_index = req_int(data, "sequence_index", minimum=1)
    capacity = req_int(data, "capacity", minimum=1)
    dws = req_dt(data, "dispatch_window_start")
    dwe = req_dt(data, "dispatch_window_end")
    if not (dwe > dws):
        raise err_invalid_request("dispatch_window_end must be after dispatch_window_start")
    lock_at = req_dt(data, "address_lock_at")
    for w in db.waves.values():
        if w["campaign_id"] == campaign_id and w["sequence_index"] == sequence_index:
            raise err_invalid_request("sequence_index must be unique per campaign")

    wave = {
        "campaign_id": campaign_id,
        "region_code": region,
        "sequence_index": sequence_index,
        "capacity": capacity,
        "assignments": [],
        "capacity_used": 0,
        "dispatch_window_start": dws,
        "dispatch_window_end": dwe,
        "address_lock_at": lock_at,
        "status": "SCHEDULED",
    }
    stamp_new(wave)
    db.waves[wave["id"]] = wave
    touch(campaign)
    return success_obj(serialize(wave), 201)


@bp.route("/waves/<wid>", methods=["GET"])
def get_wave(wid):
    require_auth(ANY_ROLE)
    w = db.waves.get(wid)
    if not w:
        raise err_not_found("wave not found")
    return success_obj(serialize(w))


@bp.route("/waves", methods=["GET"])
def list_waves():
    require_auth(ANY_ROLE)
    items = list(db.waves.values())
    args = request.args
    if args.get("campaign_id"):
        items = [w for w in items if w["campaign_id"] == args["campaign_id"]]
    if args.get("region_code"):
        items = [w for w in items if w["region_code"] == args["region_code"]]
    if args.get("status"):
        items = [w for w in items if w["status"] == args["status"]]
    return paginate(items)


ASSIGNMENT_ACTIONS = {"assign", "auto_populate", "reassign", "remove"}
ALL_ACTIONS = {"open", "rebalance", "close", "dispatch", "cancel",
               "assign", "auto_populate", "reassign", "remove",
               "pick", "ship", "deliver"}


def _assign_pledge_to_wave(wave, pledge, campaign):
    """Add ASSIGNED entry, set pledge WAVE_ASSIGNED."""
    wave["assignments"].append({"pledge_id": pledge["id"], "status": "ASSIGNED"})
    _sync_capacity(wave)
    pledge["fulfillment_status"] = "WAVE_ASSIGNED"
    pledge["assigned_wave_id"] = wave["id"]
    touch(pledge)


def _remove_pledge_from_wave(wave, pledge, new_entry_status):
    for entry in wave["assignments"]:
        if entry["pledge_id"] == pledge["id"] and entry["status"] == "ASSIGNED":
            entry["status"] = new_entry_status
    _sync_capacity(wave)
    pledge["fulfillment_status"] = "QUEUED"
    pledge["assigned_wave_id"] = None
    touch(pledge)


@bp.route("/waves/<wid>/transition", methods=["POST"])
def wave_transition(wid):
    require_auth({"FulfillmentOperator"})
    wave = db.waves.get(wid)
    if not wave:
        raise err_not_found("wave not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ALL_ACTIONS:
        raise err_unknown_action(f"unknown action {action}")
    campaign = db.campaigns.get(wave["campaign_id"])
    now = now_dt()

    if action in ASSIGNMENT_ACTIONS:
        check_occ(campaign, data)

    if action == "open":
        if wave["status"] != "SCHEDULED":
            raise err_invalid_state("open requires SCHEDULED")
        if campaign["status"] not in ("IN_PRODUCTION", "FULFILLING"):
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "campaign not IN_PRODUCTION")
        if not any(
            s["region_code"] == wave["region_code"]
            and s["status"] in ("CLEARED", "DELIVERED")
            and (db.production_runs.get(s["production_run_id"]) or {}).get("campaign_id") == campaign["id"]
            for s in db.freight_shipments.values()
        ):
            raise ApiError("ERR_FREIGHT_NOT_CLEARED", 409, "no cleared freight for region")
        for w2 in db.waves.values():
            if (w2["campaign_id"] == campaign["id"] and w2["id"] != wave["id"]
                    and w2["sequence_index"] < wave["sequence_index"]
                    and w2["status"] in ("SCHEDULED", "OPEN", "CLOSED")):
                raise ApiError("ERR_WAVE_OUT_OF_SEQUENCE", 409, "lower sequence wave not dispatched")
        wave["status"] = "OPEN"
        touch(wave)
        if campaign["status"] == "IN_PRODUCTION":
            campaign["status"] = "FULFILLING"
        touch(campaign)

    elif action == "rebalance":
        if wave["status"] != "OPEN":
            raise err_invalid_state("rebalance requires OPEN")
        if _wave_capacity_used(wave) != 0:
            raise ApiError("ERR_WAVE_NOT_EMPTY", 409, "wave not empty")
        new_cap = opt_int(data, "capacity")
        if new_cap is not None:
            if new_cap < 1:
                raise err_invalid_request("capacity must be >= 1")
            wave["capacity"] = new_cap
        dws = opt_dt(data, "dispatch_window_start")
        dwe = opt_dt(data, "dispatch_window_end")
        if dws is not None:
            wave["dispatch_window_start"] = dws
        if dwe is not None:
            wave["dispatch_window_end"] = dwe
        if not (wave["dispatch_window_end"] > wave["dispatch_window_start"]):
            raise err_invalid_request("dispatch_window_end must be after dispatch_window_start")
        wave["status"] = "SCHEDULED"
        touch(wave)

    elif action == "close":
        if wave["status"] != "OPEN":
            raise err_invalid_state("close requires OPEN")
        if _wave_capacity_used(wave) == 0:
            raise err_invalid_state("close requires capacity_used > 0")
        for entry in wave["assignments"]:
            if entry["status"] != "ASSIGNED":
                continue
            p = db.pledges.get(entry["pledge_id"])
            if not p or p["fulfillment_status"] != "DELIVERED":
                raise err_invalid_state("all assigned pledges must be DELIVERED")
        wave["status"] = "CLOSED"
        touch(wave)

    elif action == "dispatch":
        if wave["status"] != "CLOSED":
            raise err_invalid_state("dispatch requires CLOSED")
        if now < wave["dispatch_window_end"]:
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "dispatch window not ended")
        wave["status"] = "DISPATCHED"
        touch(wave)
        waves = [w for w in db.waves.values() if w["campaign_id"] == campaign["id"]]
        if waves and all(w["status"] == "DISPATCHED" for w in waves):
            from campaign_routes import _finalize_retail_release
            _finalize_retail_release(campaign)
            touch(campaign)

    elif action == "cancel":
        if wave["status"] != "SCHEDULED":
            raise err_invalid_state("cancel requires SCHEDULED")
        if _wave_capacity_used(wave) != 0:
            raise ApiError("ERR_WAVE_NOT_EMPTY", 409, "wave not empty")
        wave["status"] = "CANCELLED"
        touch(wave)

    elif action == "assign":
        if wave["status"] != "OPEN":
            raise err_invalid_state("assign requires OPEN wave")
        pid = data.get("pledge_id")
        if not isinstance(pid, str):
            raise err_invalid_request("pledge_id is required")
        p = db.pledges.get(pid)
        if not p or p["campaign_id"] != campaign["id"]:
            raise err_not_found("pledge not found")
        if not (p["charge_status"] == "CHARGED"
                and p["address_status"] == "CONFIRMED"
                and p["fulfillment_status"] == "QUEUED"
                and p["region_code"] == wave["region_code"]):
            raise err_invalid_state("pledge not eligible for assignment")
        if _wave_capacity_used(wave) >= wave["capacity"]:
            raise ApiError("ERR_WAVE_CAPACITY_FULL", 409, "wave capacity full")
        _assign_pledge_to_wave(wave, p, campaign)
        touch(wave)
        touch(campaign)

    elif action == "auto_populate":
        if wave["status"] != "OPEN":
            raise err_invalid_state("auto_populate requires OPEN wave")
        eligible = [
            p for p in db.pledges.values()
            if p["campaign_id"] == campaign["id"]
            and p["charge_status"] == "CHARGED"
            and p["address_status"] == "CONFIRMED"
            and p["fulfillment_status"] == "QUEUED"
            and p["region_code"] == wave["region_code"]
        ]
        eligible.sort(key=lambda p: (p["created_at"], p["updated_at"], p.get("_seq", 0)))
        for p in eligible:
            if _wave_capacity_used(wave) >= wave["capacity"]:
                break
            _assign_pledge_to_wave(wave, p, campaign)
        touch(wave)
        touch(campaign)

    elif action == "reassign":
        if wave["status"] != "OPEN":
            raise err_invalid_state("reassign requires OPEN source wave")
        pid = data.get("pledge_id")
        target_id = data.get("target_wave_id")
        if not isinstance(pid, str):
            raise err_invalid_request("pledge_id is required")
        if not isinstance(target_id, str):
            raise err_invalid_request("target_wave_id is required")
        p = db.pledges.get(pid)
        if not p or p["campaign_id"] != campaign["id"]:
            raise err_not_found("pledge not found")
        target = db.waves.get(target_id)
        if not target or target["campaign_id"] != campaign["id"]:
            raise err_not_found("target wave not found")
        if not (p["fulfillment_status"] == "WAVE_ASSIGNED" and p["assigned_wave_id"] == wave["id"]):
            raise err_invalid_state("pledge not assigned to this wave")
        if p["region_code"] != target["region_code"]:
            raise err_invalid_state("pledge region does not match target wave")
        if _wave_capacity_used(target) >= target["capacity"]:
            raise ApiError("ERR_WAVE_CAPACITY_FULL", 409, "target wave capacity full")
        _remove_pledge_from_wave(wave, p, "REASSIGNED")
        _assign_pledge_to_wave(target, p, campaign)
        touch(wave)
        touch(target)
        touch(campaign)

    elif action == "remove":
        if wave["status"] != "OPEN":
            raise err_invalid_state("remove requires OPEN wave")
        pid = data.get("pledge_id")
        if not isinstance(pid, str):
            raise err_invalid_request("pledge_id is required")
        p = db.pledges.get(pid)
        if not p or p["campaign_id"] != campaign["id"]:
            raise err_not_found("pledge not found")
        if not (p["fulfillment_status"] == "WAVE_ASSIGNED" and p["assigned_wave_id"] == wave["id"]):
            raise err_invalid_state("pledge not assigned to this wave")
        _remove_pledge_from_wave(wave, p, "REMOVED")
        touch(wave)
        touch(campaign)

    elif action == "pick":
        if wave["status"] != "OPEN":
            raise err_invalid_state("pick requires OPEN wave")
        pid = data.get("pledge_id")
        if not isinstance(pid, str):
            raise err_invalid_request("pledge_id is required")
        p = db.pledges.get(pid)
        if not p or p["campaign_id"] != campaign["id"]:
            raise err_not_found("pledge not found")
        if not (p["fulfillment_status"] == "WAVE_ASSIGNED" and p["assigned_wave_id"] == wave["id"]):
            raise err_invalid_state("pledge not WAVE_ASSIGNED on this wave")
        if not (wave["dispatch_window_start"] <= now < wave["dispatch_window_end"]):
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "outside dispatch window")
        p["fulfillment_status"] = "PICKED"
        touch(p)
        touch(wave)

    elif action == "ship":
        if wave["status"] != "OPEN":
            raise err_invalid_state("ship requires OPEN wave")
        pid = data.get("pledge_id")
        if not isinstance(pid, str):
            raise err_invalid_request("pledge_id is required")
        p = db.pledges.get(pid)
        if not p or p["campaign_id"] != campaign["id"]:
            raise err_not_found("pledge not found")
        if not (p["fulfillment_status"] == "PICKED" and p["assigned_wave_id"] == wave["id"]):
            raise err_invalid_state("pledge not PICKED on this wave")
        for s in db.freight_shipments.values():
            run = db.production_runs.get(s["production_run_id"])
            if run and run["campaign_id"] == campaign["id"] and s["region_code"] == wave["region_code"]:
                if s["status"] not in ("CLEARED", "DELIVERED"):
                    raise ApiError("ERR_FREIGHT_NOT_CLEARED", 409, "regional freight not cleared")
        p["fulfillment_status"] = "SHIPPED"
        touch(p)
        touch(wave)

    elif action == "deliver":
        pid = data.get("pledge_id")
        if not isinstance(pid, str):
            raise err_invalid_request("pledge_id is required")
        p = db.pledges.get(pid)
        if not p or p["campaign_id"] != campaign["id"]:
            raise err_not_found("pledge not found")
        if not (p["fulfillment_status"] == "SHIPPED" and p["assigned_wave_id"] == wave["id"]):
            raise err_invalid_state("pledge not SHIPPED on this wave")
        p["fulfillment_status"] = "DELIVERED"
        touch(p)
        assigned = [e for e in wave["assignments"] if e["status"] == "ASSIGNED"]
        if wave["status"] == "OPEN" and assigned:
            all_delivered = all(
                (db.pledges.get(e["pledge_id"]) or {}).get("fulfillment_status") == "DELIVERED"
                for e in assigned
            )
            if all_delivered:
                wave["status"] = "CLOSED"
        touch(wave)

    return success_obj(serialize(wave))
